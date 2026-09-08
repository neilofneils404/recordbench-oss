"""Static assets retain the browser's TLS origin behind a proxy."""
from pathlib import Path
import re
from urllib.parse import urljoin

import pytest
from jinja2 import Environment
from starlette.datastructures import URL

TEMPLATES = Path(__file__).parents[1] / 'src/case_intelligence/templates'


@pytest.mark.parametrize('template', ['workbench_base.html', 'workspace.html', 'source.html'])
def test_static_assets_preserve_external_https_port(template):
    expressions = re.findall(r'{{\s*(url_for\(\s*[\'"]static[\'"][^}]+)\s*}}', (TEMPLATES / template).read_text())
    assert expressions
    # The internal proxy request has HTTP and no external port.
    def url_for(name, path):
        return URL('http://localhost/static/' + path.lstrip('/'))
    for expression in expressions:
        asset = Environment().from_string('{{ ' + expression + ' }}').render(url_for=url_for)
        assert urljoin('https://localhost:8443/matters/synthetic/home', asset).startswith('https://localhost:8443/static/')
