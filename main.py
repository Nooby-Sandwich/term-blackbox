import sys
from blackbox import server, client

def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py [server|client]")
        sys.exit(1)

    mode = sys.argv[1]
    
    if mode == "server":
        server.start_server()
    elif mode == "client":
        client.start_client()
    else:
        print(f"Unknown mode: {mode}")
        print("Usage: python main.py [server|client]")

if __name__ == "__main__":
    main()