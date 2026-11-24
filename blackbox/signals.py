"""Signal and crash handling for the flight recorder."""

import signal
import sys

def setup_signal_handlers(cleanup_function):
    """
    Listens for termination signals and runs the cleanup function.
    """
    def handler(signum, frame):
        print(f"\n[Black Box] Caught signal {signum}. FLushing buffer before exit...")
        cleanup_function()
        sys.exit(0)

    # SIGNINT is Ctrl+C
    signal.signal(signal.SIGINT, handler)

    # SIGTERM is what the OS sends when it wants to kill your app (e.g. closing window)
    signal.signal(signal.SIGTERM, handler)

    # On Windows, sometimes closing the console sends SIGHUP and CTRL_CLOSE_EVENT
    try:
        signal.signal(signal.SIGHUP, handler)
    except:
        # SIGHUP doesn't always exist on Windows, so we skip it if it errors
        pass


