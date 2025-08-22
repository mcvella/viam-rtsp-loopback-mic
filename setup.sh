#!/bin/sh
cd `dirname $0`

# Install system dependencies for RTSP loopback microphone
echo "Installing system dependencies..."
if command -v apt-get >/dev/null; then
    echo "Detected Debian/Ubuntu, installing FFmpeg and ALSA utilities..."
    SUDO="sudo"
    if ! command -v $SUDO >/dev/null; then
        SUDO=""
    fi
    $SUDO apt-get update -qq >/dev/null 2>&1
    $SUDO apt-get install -qqy ffmpeg alsa-utils >/dev/null 2>&1
    echo "System dependencies installed successfully."
elif command -v yum >/dev/null; then
    echo "Detected RHEL/CentOS, installing FFmpeg and ALSA utilities..."
    SUDO="sudo"
    if ! command -v $SUDO >/dev/null; then
        SUDO=""
    fi
    $SUDO yum install -y ffmpeg alsa-utils >/dev/null 2>&1
    echo "System dependencies installed successfully."
elif command -v dnf >/dev/null; then
    echo "Detected Fedora, installing FFmpeg and ALSA utilities..."
    SUDO="sudo"
    if ! command -v $SUDO >/dev/null; then
        SUDO=""
    fi
    $SUDO dnf install -y ffmpeg alsa-utils >/dev/null 2>&1
    echo "System dependencies installed successfully."
else
    echo "Warning: Could not detect package manager. Please ensure FFmpeg and ALSA utilities are installed manually."
fi

# Create a virtual environment to run our code
VENV_NAME="venv"
PYTHON="$VENV_NAME/bin/python"
ENV_ERROR="This module requires Python >=3.8, pip, and virtualenv to be installed."

if ! python3 -m venv $VENV_NAME >/dev/null 2>&1; then
    echo "Failed to create virtualenv."
    if command -v apt-get >/dev/null; then
        echo "Detected Debian/Ubuntu, attempting to install python3-venv automatically."
        SUDO="sudo"
        if ! command -v $SUDO >/dev/null; then
            SUDO=""
        fi
		if ! apt info python3-venv >/dev/null 2>&1; then
			echo "Package info not found, trying apt update"
			$SUDO apt -qq update >/dev/null
		fi
        $SUDO apt install -qqy python3-venv >/dev/null 2>&1
        if ! python3 -m venv $VENV_NAME >/dev/null 2>&1; then
            echo $ENV_ERROR >&2
            exit 1
        fi
    else
        echo $ENV_ERROR >&2
        exit 1
    fi
fi

# remove -U if viam-sdk should not be upgraded whenever possible
# -qq suppresses extraneous output from pip
echo "Virtualenv found/created. Installing/upgrading Python packages..."
if ! [ -f .installed ]; then
    if ! $PYTHON -m pip install -r requirements.txt -Uqq; then
        exit 1
    else
        touch .installed
    fi
fi
