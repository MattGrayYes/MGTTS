# MGTTS - Matt G's Text To Speech

I've got [Piper](https://github.com/linuxserver/docker-piper) running in a docker container, wanted to easily try out phrases in different voices, and couldn't find a simple UI for it.

## Requirements
- Access to a TTS engine via Wyoming server
- Python3
- Audio Player:
  - The script tries any of the following audio players
    - SoX
    - ffplay (part of ffmpeg)
    - paplay
    - afplay
  - If it fails, it will save a WAV file in the current directory

This has only been tested on Mac OS Sequoia 15.7.3

## How To Use

The only info that's required is:
- Server address:port
- Text

`./mgtts.py --server 10.0.0.69:10200 "Hello World"`

To make it cleaner, define the server and a default model in the config file
```
server=10.0.0.69:10200
model=cy_GB-gwryw_gogleddol-medium
```

This will now use the defined server and model by default.

`./mgtts.py 'I love a bit of bara brith with my cup of tea.'`

But you can override these settings with the command-line options

`./mgtts.py --model en_GB-vctk-medium --speaker 23 'I like a nice thick slice of battenburg with mine!'`

`./mgtts.py --model en_US-ljspeech-medium -o gunsblazing.wav 'All I need is coffee and a high caliber rifle!'`

### Command Line Options

Beware of `--speaker`. Many voice models only have one speaker, so you'll be best off leaving this blank, or at 0.

```
usage: mgtts.py [-h] [-w SERVER:PORT] [-m MODEL] [-s SPEAKER] [-d] text

Speak text via a Wyoming / Piper TTS server

positional arguments:
  text                          Text to speak

options:
  -h, --help                    show this help message and exit
  -w, --wyoming SERVER:PORT     Wyoming TTS server address (host:port)
  -m, --model MODEL             Model (voice) name to use
  -s, --speaker SPEAKER         Speaker number
  -o, --outfile FILE_PATH       Output audio as WAV file instead of playing
  -d, --debug                   Print debug info to stderr
```
## Piper Voices
If you're using Piper TTS, [rhasspy's Piper Voice Samples](https://rhasspy.github.io/piper-samples/#en_GB-vctk-medium) is a handy page to find a voice model that you'd like to use.

I've also included a CSV list of the [VCTK](https://datashare.ed.ac.uk/handle/10283/2950) speakers, with their descriptions and speaker numbers.

## AI Disclosure
I made this with help from Claude Opus 4.6
