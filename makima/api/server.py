import uvicorn
import argparse

def main():
    parser = argparse.ArgumentParser(description="Start Makima Agent API Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default 8000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind")
    args = parser.parse_args()

    print(f"Starting Makima Agent API Server on http://{args.host}:{args.port}")
    uvicorn.run("makima.api.app:app", host=args.host, port=args.port, reload=False)

if __name__ == "__main__":
    main()
