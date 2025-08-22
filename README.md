# Module rtsp-loopback-mic 

A Viam sensor component that streams audio from an RTSP URL to a loopback audio device, making it available as a virtual microphone input. This module automatically sets up the ALSA loopback device and uses FFmpeg to stream the RTSP audio feed.

## Model mcvella:rtsp-loopback-mic:rtsp-loopback-mic

This sensor component creates a virtual microphone by streaming audio from an RTSP source to a loopback audio device. It automatically handles the setup of the ALSA loopback module and manages the FFmpeg streaming process.

### System Requirements

- Linux system with ALSA support
- FFmpeg installed (`ffmpeg` command available)
- ALSA utilities (`arecord` command available)
- Root access or sudo privileges for loading kernel modules

### Configuration
The following attribute template can be used to configure this model:

```json
{
  "rtsp_url": "rtsp://username:password@ip:port/stream"
}
```

#### Attributes

The following attributes are available for this model:

| Name       | Type   | Inclusion | Description                                    |
|------------|--------|-----------|------------------------------------------------|
| `rtsp_url` | string | Required  | The RTSP URL to stream audio from              |

#### Example Configuration

```json
{
  "rtsp_url": "rtsp://admin:password@192.168.1.100:554/audio"
}
```

### How It Works

1. **Module Loading**: Automatically loads the `snd-aloop` kernel module to create a loopback audio device
2. **Device Detection**: Uses `arecord -l` to find available audio devices and identifies the loopback device
3. **Audio Streaming**: Runs FFmpeg to stream the RTSP audio to the loopback device using ALSA
4. **Status Monitoring**: Provides real-time status and FFmpeg output through sensor readings

### Sensor Readings

The `get_readings()` method returns the following information:

| Reading Name        | Type    | Description                                    |
|---------------------|---------|------------------------------------------------|
| `streaming_status`  | boolean | Whether the FFmpeg stream is currently active  |
| `rtsp_url`          | string  | The configured RTSP URL                        |
| `loopback_device`   | string  | The ALSA device number being used              |
| `ffmpeg_output`     | string  | The latest FFmpeg output line (includes stream info) |
| `ffmpeg_process_id` | integer | The process ID of the running FFmpeg process   |

### Example FFmpeg Output

The `ffmpeg_output` reading will contain lines like:
```
Output #0, alsa, to 'hw:4,0,0':
  Metadata:
    title           : Session streamed by "TP-LINK RTSP Server"
    encoder         : Lavf58.45.100
    Stream #0:0: Audio: pcm_s16le, 8000 Hz, mono, s16, 128 kb/s
    Metadata:
      encoder         : Lavc58.91.100 pcm_s16le
size=N/A time=00:00:15.30 bitrate=N/A speed=1.14x
```

### DoCommand

This model implements DoCommand for controlling the audio stream:

#### Supported Commands

| Command        | Description                    |
|----------------|--------------------------------|
| `start_stream` | Start the FFmpeg audio stream  |
| `stop_stream`  | Stop the FFmpeg audio stream   |
| `restart_stream` | Restart the FFmpeg audio stream |

#### Example DoCommand

```json
{
  "command": "start_stream"
}
```

```json
{
  "command": "stop_stream"
}
```

```json
{
  "command": "restart_stream"
}
```

### Installation and Setup

1. **Install Dependencies**:
   ```bash
   sudo apt-get update
   sudo apt-get install ffmpeg alsa-utils
   ```

2. **Load ALSA Loopback Module** (optional, module does this automatically):
   ```bash
   sudo modprobe snd-aloop
   ```

3. **Configure in Viam**:
   - Add the module to your robot configuration
   - Provide the RTSP URL in the attributes
   - The module will automatically start streaming when configured

### Troubleshooting

- **Permission Issues**: Ensure the user running viam-server has permission to load kernel modules or run `modprobe`
- **FFmpeg Not Found**: Install FFmpeg using your system's package manager
- **No Audio Devices**: Check that ALSA is properly installed and configured
- **RTSP Connection Issues**: Verify the RTSP URL is accessible and credentials are correct

### Security Notes

- RTSP URLs with credentials are stored in the configuration
- The module runs FFmpeg as a subprocess with the same privileges as viam-server
- Consider using environment variables or secure credential storage for production deployments
