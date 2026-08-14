# ruff: noqa: N999

import os

bind = f"0.0.0.0:{os.environ.get('PYPISERVER_PORT', '8080')}"
workers = 2
accesslog = "-"
errorlog = "-"
certfile = "/data/tls/certificate.pem"
keyfile = "/data/tls/private-key.pem"
