"""Private stdin/stdout protocol for one article's native extraction, never fetching URLs."""
import faulthandler
import json
import os
import sys

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024


def extract_payload(html_bytes, *, metadata=False):
    # Only this disposable process imports native parsers in production.
    import trafilatura
    try:
        text = trafilatura.extract(html_bytes, output_format='txt')
    except Exception:
        text = None
    title = None
    if metadata:
        try:
            meta = trafilatura.extract_metadata(html_bytes)
            title = meta.title if meta else None
        except Exception:
            pass
    return {'text': text, 'title': title}


def main():
    # Native crashes must not leave a core image containing article HTML in CI.
    try:
        import resource
    except ImportError:  # Windows has no resource module.
        pass
    else:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # Keep a private protocol handle. Silence Python and native fd writes before
    # importing parsers so logs cannot leak HTML or fill the parent's pipe.
    with os.fdopen(os.dup(sys.stdout.fileno()), 'wb') as protocol:
        with open(os.devnull, 'wb') as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
            os.dup2(sink.fileno(), sys.stderr.fileno())
        faulthandler.enable(all_threads=False)
        try:
            html_bytes = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
            if len(html_bytes) > MAX_INPUT_BYTES:
                return 2
            value = extract_payload(html_bytes, metadata='--metadata' in sys.argv[1:])
            encoded = json.dumps(value, ensure_ascii=False).encode('utf-8')
            if len(encoded) > MAX_OUTPUT_BYTES:
                return 3
            protocol.write(encoded)
            return 0
        except Exception:
            return 4


if __name__ == '__main__':
    raise SystemExit(main())
