import asyncio
import subprocess
import re
import time
from typing import (Any, ClassVar, Dict, Final, List, Mapping, Optional,
                    Sequence, Tuple)

from typing_extensions import Self
from viam.components.sensor import *
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import Geometry, ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.utils import SensorReading, ValueTypes, struct_to_dict


class RtspLoopbackMic(Sensor, EasyResource):
    # To enable debug-level logging, either run viam-server with the --debug option,
    # or configure your resource/machine to display debug logs.
    MODEL: ClassVar[Model] = Model(
        ModelFamily("mcvella", "rtsp-loopback-mic"), "rtsp-loopback-mic"
    )


    rtsp_url: Optional[str] = None
    ffmpeg_process: Optional[asyncio.subprocess.Process] = None
    loopback_device: Optional[str] = None
    ffmpeg_output: str = ""
    is_streaming: bool = False
    
    # Simple resilience attributes
    last_activity_time: float = 0.0
    restart_count: int = 0
    max_restarts: int = 3
    restart_cooldown: float = 10.0  # seconds
    last_restart_time: float = 0.0

    @classmethod
    def new(
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Self:
        """This method creates a new instance of this Sensor component.
        The default implementation sets the name from the `config` parameter and then calls `reconfigure`.

        Args:
            config (ComponentConfig): The configuration for this resource
            dependencies (Mapping[ResourceName, ResourceBase]): The dependencies (both required and optional)

        Returns:
            Self: The resource
        """
        return super().new(config, dependencies)

    @classmethod
    def validate_config(
        cls, config: ComponentConfig
    ) -> Tuple[Sequence[str], Sequence[str]]:
        """This method allows you to validate the configuration object received from the machine,
        as well as to return any required dependencies or optional dependencies based on that `config`.

        Args:
            config (ComponentConfig): The configuration for this resource

        Returns:
            Tuple[Sequence[str], Sequence[str]]: A tuple where the
                first element is a list of required dependencies and the
                second element is a list of optional dependencies
        """
        # Validate that rtsp_url is provided in attributes
        attributes = struct_to_dict(config.attributes)
        if not attributes or "rtsp_url" not in attributes:
            raise ValueError("rtsp_url is required in attributes")
        
        rtsp_url = attributes.get("rtsp_url")
        if not rtsp_url or not isinstance(rtsp_url, str):
            raise ValueError("rtsp_url must be a non-empty string")
        
        return [], []

    def reconfigure(
        self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ):
        """This method allows you to dynamically update your service when it receives a new `config` object.

        Args:
            config (ComponentConfig): The new configuration
            dependencies (Mapping[ResourceName, ResourceBase]): Any dependencies (both required and optional)
        """
        # Clean up any existing FFmpeg processes from previous module instances
        asyncio.create_task(self.cleanup_old_processes())
        
        # Stop existing stream if running
        if self.is_streaming:
            asyncio.create_task(self.stop_stream())
        
        # Update RTSP URL
        attributes = struct_to_dict(config.attributes)
        if attributes and "rtsp_url" in attributes:
            self.rtsp_url = attributes.get("rtsp_url")
            self.logger.info(f"RTSP URL updated to: {self.rtsp_url}")
        
        # Start new stream
        if self.rtsp_url:
            asyncio.create_task(self.start_stream())

    async def setup_loopback_device(self) -> str:
        """Set up the loopback audio device and return the device number."""
        try:
            # Load the snd-aloop module
            self.logger.info("Loading snd-aloop module...")
            result = await asyncio.create_subprocess_exec(
                "modprobe", "snd-aloop",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await result.communicate()
            
            # Get available audio devices
            self.logger.info("Getting audio device list...")
            result = await asyncio.create_subprocess_exec(
                "arecord", "-l",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode != 0:
                raise RuntimeError(f"Failed to get audio devices: {stderr.decode()}")
            
            # Parse the output to find loopback device
            output = stdout.decode()
            self.logger.info(f"Audio devices found:\n{output}")
            
            # Look for loopback device (usually shows as "Loopback" in the name)
            lines = output.split('\n')
            for line in lines:
                if 'Loopback' in line or 'loopback' in line:
                    # Extract device number from line like "card 4: Loopback [Loopback], device 0: Loopback PCM [Loopback PCM]"
                    match = re.search(r'card (\d+):', line)
                    if match:
                        device_num = match.group(1)
                        self.logger.info(f"Found loopback device: {device_num}")
                        return device_num
            
            # If no loopback device found, try to use the last available device
            matches = re.findall(r'card (\d+):', output)
            if matches:
                device_num = matches[-1]
                self.logger.info(f"Using last available device: {device_num}")
                return device_num
            
            raise RuntimeError("No suitable audio device found")
            
        except Exception as e:
            self.logger.error(f"Failed to setup loopback device: {e}")
            raise

    async def start_stream(self):
        """Start the ffmpeg stream to the loopback device."""
        if not self.rtsp_url:
            self.logger.error("No RTSP URL configured")
            return
        
        try:
            # Stop existing stream if running
            if self.is_streaming:
                await self.stop_stream()
            
            # Clean up any old processes that might conflict
            await self.cleanup_old_processes()
            
            # Setup loopback device
            self.loopback_device = await self.setup_loopback_device()
            
            # Build ffmpeg command with basic resilience
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", self.rtsp_url,
                "-f", "alsa",
                f"hw:{self.loopback_device},0,0",
                "-y",  # Overwrite output file if it exists
                "-reconnect", "1",  # Enable reconnection
                "-reconnect_streamed", "1",  # Reconnect for streamed content
                "-reconnect_delay_max", "10"  # Max delay between reconnection attempts
            ]
            
            self.logger.info(f"Starting ffmpeg stream: {' '.join(ffmpeg_cmd)}")
            
            # Start ffmpeg process
            self.ffmpeg_process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.is_streaming = True
            self.ffmpeg_output = ""
            self.last_activity_time = time.time()
            self.restart_count += 1
            self.last_restart_time = time.time()
            
            # Start monitoring the output
            asyncio.create_task(self.monitor_ffmpeg_output())
            asyncio.create_task(self.periodic_process_check())
            
            self.logger.info("FFmpeg stream started successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to start stream: {e}")
            self.is_streaming = False

    async def stop_stream(self):
        """Stop the ffmpeg stream."""
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.terminate()
                await asyncio.wait_for(self.ffmpeg_process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.logger.warning("FFmpeg process didn't terminate gracefully, killing it")
                self.ffmpeg_process.kill()
                await self.ffmpeg_process.wait()
            except Exception as e:
                self.logger.error(f"Error stopping ffmpeg process: {e}")
            finally:
                self.ffmpeg_process = None
                self.is_streaming = False
                self.logger.info("FFmpeg stream stopped")
        
        # Clean up any processes that might be holding the ALSA device
        await self.cleanup_alsa_devices()

    async def cleanup_alsa_devices(self):
        """Clean up processes that might be holding ALSA devices open."""
        try:
            # Kill any FFmpeg processes that might be holding the loopback device
            cleanup_cmd = [
                "pkill", "-f", f"ffmpeg.*hw:{self.loopback_device},0,0"
            ]
            
            result = await asyncio.create_subprocess_exec(
                *cleanup_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await result.wait()
            
            # Give ALSA a moment to release the device
            await asyncio.sleep(1)
            
            self.logger.info("ALSA device cleanup completed")
            
        except Exception as e:
            self.logger.warning(f"Error during ALSA cleanup: {e}")

    async def cleanup_old_processes(self):
        """Clean up FFmpeg processes from previous module instances."""
        try:
            self.logger.info("Cleaning up old FFmpeg processes from previous module instances")
            
            # Kill any FFmpeg processes that might be from previous module instances
            cleanup_cmd = [
                "pkill", "-f", "ffmpeg.*-f alsa.*hw:"
            ]
            
            result = await asyncio.create_subprocess_exec(
                *cleanup_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await result.wait()
            
            # Give processes time to terminate
            await asyncio.sleep(2)
            
            # Also clean up any processes with our specific RTSP URL if configured
            if self.rtsp_url:
                url_cleanup_cmd = [
                    "pkill", "-f", f"ffmpeg.*{self.rtsp_url}"
                ]
                
                result = await asyncio.create_subprocess_exec(
                    *url_cleanup_cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await result.wait()
                await asyncio.sleep(1)
            
            self.logger.info("Old FFmpeg processes cleanup completed")
            
        except Exception as e:
            self.logger.warning(f"Error during old processes cleanup: {e}")

    async def check_process_status(self):
        """Check if the FFmpeg process is actually running and sync state."""
        if self.ffmpeg_process:
            try:
                # Check if process is still alive
                if self.ffmpeg_process.returncode is None:
                    # Process is still running
                    if not self.is_streaming:
                        self.logger.info("FFmpeg process is running, syncing streaming status")
                        self.is_streaming = True
                    return True
                else:
                    # Process has terminated, but check if there's another one running
                    running_pid = await self.find_running_ffmpeg()
                    if running_pid:
                        self.logger.info(f"Process state sync: Found different FFmpeg process running: {running_pid} (was tracking: {self.ffmpeg_process.pid if self.ffmpeg_process else 'None'})")
                        self.is_streaming = True
                        return True
                    else:
                        if self.is_streaming:
                            self.logger.info("FFmpeg process has terminated, updating status")
                            self.is_streaming = False
                        return False
            except Exception as e:
                self.logger.error(f"Error checking process status: {e}")
                return False
        else:
            # No tracked process, but check if there's one running
            running_pid = await self.find_running_ffmpeg()
            if running_pid:
                self.logger.info(f"Process state sync: Found running FFmpeg process but not tracking it: {running_pid}")
                self.is_streaming = True
                return True
            else:
                if self.is_streaming:
                    self.logger.warning("No FFmpeg process but streaming status is True, correcting")
                    self.is_streaming = False
                return False

    async def find_running_ffmpeg(self):
        """Find and attach to a running FFmpeg process for this RTSP stream."""
        try:
            # Look for FFmpeg processes with our RTSP URL
            cmd = ["pgrep", "-f", f"ffmpeg.*{self.rtsp_url}"]
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            stdout, _ = await result.communicate()
            
            if result.returncode == 0 and stdout.strip():
                pid = stdout.strip().decode()
                self.logger.info(f"Found running FFmpeg process: {pid}")
                return int(pid)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error finding running FFmpeg: {e}")
            return None

    async def periodic_process_check(self):
        """Periodically check process status to catch state mismatches."""
        while self.is_streaming:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                # Check if our tracked process is still valid
                if self.ffmpeg_process and self.ffmpeg_process.returncode is not None:
                    # Our tracked process has died, look for a new one
                    self.logger.info("Tracked FFmpeg process has terminated, looking for replacement")
                    running_pid = await self.find_running_ffmpeg()
                    if running_pid:
                        self.logger.info(f"Found replacement FFmpeg process: {running_pid}")
                        # Note: We can't easily reattach to an existing process, 
                        # but we can at least update our status
                        self.is_streaming = True
                    else:
                        self.logger.warning("No replacement FFmpeg process found")
                        self.is_streaming = False
                        break
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in periodic process check: {e}")

    async def monitor_ffmpeg_output(self):
        """Monitor ffmpeg output and store it for get_readings."""
        if not self.ffmpeg_process:
            return
        
        try:
            while self.is_streaming and self.ffmpeg_process:
                # Read stderr (ffmpeg outputs progress to stderr)
                line = await self.ffmpeg_process.stderr.readline()
                if not line:
                    break
                
                line_str = line.decode().strip()
                if line_str:
                    self.ffmpeg_output = line_str
                    self.last_activity_time = time.time()  # Update activity timestamp
                    self.logger.debug(f"FFmpeg output: {line_str}")
                    
                    # Check for error conditions that require restart
                    if any(error_indicator in line_str.lower() for error_indicator in 
                           ['connection refused', 'timeout', 'no route to host', 
                            'connection reset', 'broken pipe', 'end of file', 'device or resource busy', 'device busy']):
                        self.logger.warning(f"FFmpeg error detected: {line_str}")
                        await self.handle_stream_failure("connection_error")
        
        except Exception as e:
            self.logger.error(f"Error monitoring ffmpeg output: {e}")
        finally:
            # Check if process is actually still running before marking as stopped
            if self.ffmpeg_process:
                try:
                    # Check if process is still alive
                    if self.ffmpeg_process.returncode is None:
                        self.logger.warning("FFmpeg monitoring stopped but process appears to still be running")
                        # Don't set is_streaming = False if process is still alive
                    else:
                        await self.ffmpeg_process.wait()
                        self.is_streaming = False
                        self.logger.info("FFmpeg process terminated")
                except Exception as e:
                    self.logger.error(f"Error checking process status: {e}")
                    self.is_streaming = False

    async def handle_stream_failure(self, failure_type: str):
        """Handle stream failures and attempt recovery."""
        self.logger.warning(f"Stream failure detected: {failure_type}")
        
        # Check restart limits
        current_time = time.time()
        if (self.restart_count >= self.max_restarts and 
            current_time - self.last_restart_time < self.restart_cooldown):
            self.logger.warning(f"Too many restarts ({self.restart_count}), waiting for cooldown")
            return
        
        # Reset restart count if enough time has passed
        if current_time - self.last_restart_time > self.restart_cooldown:
            self.restart_count = 0
        
        # Attempt restart if within limits
        if self.restart_count < self.max_restarts:
            self.logger.info(f"Attempting stream restart ({self.restart_count + 1}/{self.max_restarts})")
            await self.stop_stream()
            
            # Extra cleanup for device busy errors
            if "device busy" in failure_type.lower() or "resource busy" in failure_type.lower():
                self.logger.info("Device busy detected, performing extra cleanup")
                await self.cleanup_alsa_devices()
                await asyncio.sleep(3)  # Longer delay for device busy issues
            
            await asyncio.sleep(2)  # Brief delay before restart
            await self.start_stream()
        else:
            self.logger.error(f"Max restart attempts reached ({self.max_restarts}), stopping recovery")
            self.is_streaming = False

    async def get_readings(
        self,
        *,
        extra: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Mapping[str, SensorReading]:
        """Get current readings from the RTSP loopback microphone.
        
        Returns:
            Mapping containing:
            - streaming_status: Whether the stream is active
            - rtsp_url: The current RTSP URL
            - loopback_device: The audio device being used
            - ffmpeg_output: The latest ffmpeg output line
            - ffmpeg_process_id: The process ID if running
        """
        # Check and sync process status
        await self.check_process_status()
        
        current_time = time.time()
        time_since_activity = current_time - self.last_activity_time if self.last_activity_time > 0 else 0
        
        readings = {
            "streaming_status": self.is_streaming,
            "rtsp_url": self.rtsp_url or "Not configured",
            "loopback_device": self.loopback_device or "Not configured",
            "loopback_device_full": f"hw:{self.loopback_device},0,0" if self.loopback_device else "Not configured",
            "ffmpeg_output": self.ffmpeg_output or "No output yet",
            "ffmpeg_process_id": self.ffmpeg_process.pid if self.ffmpeg_process else None,
            "last_activity_seconds": round(time_since_activity, 1),
            "restart_count": self.restart_count
        }
        
        return readings

    async def do_command(
        self,
        command: Mapping[str, ValueTypes],
        *,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Mapping[str, ValueTypes]:
        """Handle custom commands for controlling the stream.
        
        Supported commands:
        - start_stream: Start the ffmpeg stream
        - stop_stream: Stop the ffmpeg stream
        - restart_stream: Restart the ffmpeg stream
        """
        cmd = command.get("command")
        
        if cmd == "start_stream":
            await self.start_stream()
            return {"status": "started"}
        elif cmd == "stop_stream":
            await self.stop_stream()
            return {"status": "stopped"}
        elif cmd == "restart_stream":
            await self.stop_stream()
            await self.start_stream()
            return {"status": "restarted"}
        elif cmd == "reset_restart_count":
            self.restart_count = 0
            self.last_restart_time = 0
            return {"status": "restart_count_reset"}
        elif cmd == "cleanup_alsa":
            await self.cleanup_alsa_devices()
            return {"status": "alsa_cleanup_completed"}
        elif cmd == "sync_process":
            await self.check_process_status()
            return {"status": "process_synced", "streaming_status": self.is_streaming}
        elif cmd == "process_status":
            running_pid = await self.find_running_ffmpeg()
            return {
                "status": "process_status",
                "tracked_pid": self.ffmpeg_process.pid if self.ffmpeg_process else None,
                "running_pid": running_pid,
                "streaming_status": self.is_streaming,
                "process_alive": self.ffmpeg_process.returncode is None if self.ffmpeg_process else False
            }
        elif cmd == "cleanup_old":
            await self.cleanup_old_processes()
            return {"status": "old_processes_cleanup_completed"}
        else:
            return {"error": f"Unknown command: {cmd}"}

    async def get_geometries(
        self, *, extra: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> List[Geometry]:
        self.logger.error("`get_geometries` is not implemented")
        raise NotImplementedError()

