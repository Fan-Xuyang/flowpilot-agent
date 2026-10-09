from pathlib import Path
import os
import sys
import uvicorn

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv)>1 else 8202
    if 'flow-pilot' == 'flow-pilot':
        os.environ['PORTAL_BASE_URL'] = f'http://127.0.0.1:{port}'
        if port != 8202:
            os.environ['ALLOW_CUSTOM_LOCAL_PORT'] = '1'
    uvicorn.run('app.main:app', host='127.0.0.1', port=port)
