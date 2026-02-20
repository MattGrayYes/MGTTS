#!/usr/bin/env python3
# Matt G Text To Speech: Yell text at a Piper TTS server via the Wyoming protocol.

import argparse
import configparser
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import wave

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wyoming.conf")


def send_event(sock, event_type, data=None, payload=None):
    # Send a Wyoming protocol event over the socket.
    header = {"type": event_type}
    if data:
        header["data"] = data
    if payload:
        header["payload_length"] = len(payload)
    header_line = json.dumps(header, separators=(",", ":")) + "\n"
    sock.sendall(header_line.encode("utf-8"))
    if payload:
        sock.sendall(payload)


def recv_event(sock):
    # Receive a Wyoming protocol event. Returns (type, data, payload)
    # Read the JSON header line (terminated by \n)
    buf = bytearray()
    while True:
        b = sock.recv(1)
        if not b:
            raise ConnectionError("Connection closed by server")
        if b == b"\n":
            break
        buf.extend(b)

    header = json.loads(buf.decode("utf-8"))
    event_type = header["type"]
    data = header.get("data", {})

    # Read additional JSON data block if present
    data_length = header.get("data_length", 0)
    if data_length > 0:
        extra_buf = bytearray()
        while len(extra_buf) < data_length:
            chunk = sock.recv(data_length - len(extra_buf))
            if not chunk:
                raise ConnectionError("Connection closed while reading data")
            extra_buf.extend(chunk)
        data.update(json.loads(extra_buf.decode("utf-8")))

    # Read binary payload if present
    payload_length = header.get("payload_length", 0)
    payload = b""
    if payload_length > 0:
        parts = []
        remaining = payload_length
        while remaining > 0:
            chunk = sock.recv(min(remaining, 65536))
            if not chunk:
                raise ConnectionError("Connection closed while reading payload")
            parts.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(parts)

    return event_type, data, payload


def start_streaming_player(player, rate, width, channels, debug=False):
    # Start a subprocess for streaming raw PCM playback.
    bits = width * 8
    err = subprocess.PIPE if debug else subprocess.DEVNULL

    if player == "sox":
        return subprocess.Popen(
            ["play", "-q", "-t", "raw", "-r", str(rate),
             "-e", "signed-integer", "-b", str(bits), "-c", str(channels), "-"],
            stdin=subprocess.PIPE, stderr=err,
        )

    if player == "ffplay":
        ch_layout = {1: "mono", 2: "stereo"}.get(channels, f"{channels}c")
        loglevel = "warning" if debug else "quiet"
        return subprocess.Popen(
            ["ffplay", "-f", f"s{bits}le", "-ar", str(rate),
             "-ch_layout", ch_layout,
             "-probesize", "32", "-analyzeduration", "0",
             "-nodisp", "-autoexit", "-loglevel", loglevel, "-i", "pipe:0"],
            stdin=subprocess.PIPE, stderr=err,
        )

    if player == "paplay":
        fmt_map = {2: "s16le", 4: "s32le"}
        return subprocess.Popen(
            ["paplay", "--raw", f"--rate={rate}",
             f"--channels={channels}", f"--format={fmt_map.get(width, 's16le')}"],
            stdin=subprocess.PIPE, stderr=err,
        )

    return None


def play_wav_buffer(pcm_data, rate, width, channels):
    # Write a WAV temp file and play with afplay (macOS fallback, non-streaming).
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    try:
        with wave.open(os.fdopen(fd, "wb"), "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(width)
            wf.setframerate(rate)
            wf.writeframes(pcm_data)
        subprocess.run(["afplay", tmp], check=True)
    finally:
        os.unlink(tmp)


def load_config():
    # Load defaults from config file
    cfg = {"server": None, "model": None, "speaker": None}
    if not os.path.exists(CONFIG_PATH):
        return cfg
    cp = configparser.ConfigParser()
    # Wrap the file contents in a [default] section so bare key=value works
    with open(CONFIG_PATH) as f:
        contents = "[default]\n" + f.read()
    cp.read_string(contents)
    for key in cfg:
        if cp.has_option("default", key):
            cfg[key] = cp.get("default", key)
    return cfg


def main():
    cfg = load_config()

    ap = argparse.ArgumentParser(
        description="Speak text via a Wyoming / Piper TTS server")
    ap.add_argument("-w", "--wyoming", metavar="SERVER:PORT", default=None,
                                       help="Wyoming TTS server address (host:port)")
    ap.add_argument("-m", "--model",   metavar="MODEL", default=None,
                                       help="Model (voice) name to use")
    ap.add_argument("-s", "--speaker", metavar="SPEAKER", default=None,
                                       help="Speaker number or name")
    ap.add_argument("-d", "--debug", action="store_true",
                                       help="Print debug info to stderr")
    ap.add_argument("text", help="Text to speak")
    args = ap.parse_args()

    # Merge: CLI overrides config
    server = args.wyoming or cfg["server"]
    voice = args.model or cfg["model"]
    speaker = args.speaker or cfg["speaker"]

    if not server:
        print(f"Error: no server specified. Use -w HOST:PORT or set server= in {CONFIG_PATH}",
              file=sys.stderr)
        sys.exit(1)

    # Parse server address
    host, port_str = server.rsplit(":", 1)
    port = int(port_str)

    # Build synthesize event data
    synth_data = {"text": args.text}
    if voice or speaker:
        v = {}
        if voice:
            v["name"] = voice
        if speaker:
            v["speaker"] = speaker
        synth_data["voice"] = v

    # Pick an audio player: prefer streaming (sox > ffplay > paplay), fallback afplay
    streaming = True
    player = None
    for name in ("sox", "ffplay", "paplay"):
        binary = "play" if name == "sox" else name
        if shutil.which(binary):
            player = name
            break
    if player is None:
        if shutil.which("afplay"):
            player = "afplay"
            streaming = False
        else:
            print("Error: no audio player found. Install sox: brew install sox",
                  file=sys.stderr)
            sys.exit(1)

    # Connect to the Wyoming server
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, port))
    except OSError as e:
        print(f"Error: cannot connect to {host}:{port} — {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # Send the synthesize request
        send_event(sock, "synthesize", synth_data)

        proc = None
        pcm_buf = bytearray()
        fmt = {"rate": 22050, "width": 2, "channels": 1}
        total_bytes = 0
        chunk_count = 0
        debug = args.debug

        # Read events until audio-stop
        while True:
            event_type, data, payload = recv_event(sock)

            if debug:
                print(f"[wyoming] event={event_type} data={data} payload={len(payload)}B",
                      file=sys.stderr)

            if event_type == "audio-start":
                fmt["rate"] = data.get("rate", 22050)
                fmt["width"] = data.get("width", 2)
                fmt["channels"] = data.get("channels", 1)
                if debug:
                    print(f"[audio] format: {fmt['rate']}Hz {fmt['width']*8}bit {fmt['channels']}ch  player={player}",
                          file=sys.stderr)
                if streaming:
                    proc = start_streaming_player(player, **fmt, debug=debug)

            elif event_type == "audio-chunk":
                if payload:
                    total_bytes += len(payload)
                    chunk_count += 1
                    if streaming and proc:
                        try:
                            proc.stdin.write(payload)
                            proc.stdin.flush()
                        except BrokenPipeError:
                            if debug:
                                print("[audio] player pipe broke", file=sys.stderr)
                            break
                    else:
                        pcm_buf.extend(payload)

            elif event_type == "audio-stop":
                if debug:
                    print(f"[audio] total: {total_bytes}B in {chunk_count} chunks",
                          file=sys.stderr)
                if streaming and proc:
                    proc.stdin.close()
                    if debug:
                        _, stderr_out = proc.communicate()
                        if stderr_out:
                            print(f"[player] {stderr_out.decode(errors='replace')}",
                                  file=sys.stderr)
                    else:
                        proc.wait()
                elif pcm_buf and fmt:
                    play_wav_buffer(bytes(pcm_buf), **fmt)
                break

    except KeyboardInterrupt:
        if proc:
            proc.terminate()
    finally:
        sock.close()


if __name__ == "__main__":
    main()
