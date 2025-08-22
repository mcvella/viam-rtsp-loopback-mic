import asyncio
from viam.module.module import Module
try:
    from models.rtsp_loopback_mic import RtspLoopbackMic
except ModuleNotFoundError:
    # when running as local module with run.sh
    from .models.rtsp_loopback_mic import RtspLoopbackMic


if __name__ == '__main__':
    asyncio.run(Module.run_from_registry())
