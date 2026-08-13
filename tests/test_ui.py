"""The graph page: no external dependencies, and no leak through the panel.

The page is the one part of the system a Python test cannot reach, so the
render is exercised headlessly under Node when it is available. The checks that
matter without Node — that the page fetches nothing from the internet — run
everywhere, because a CDN reference is exactly what would fail silently in the
locked-down network this is meant to be demoed in.
"""

import json
import re
import shutil
import subprocess
import tempfile

import pytest

from tacit.local_store import LocalStore
from tacit.models import Visibility
from tacit.service import MemoryService
from tacit.ontology import Entity, Ontology
from tacit.ui import PAGE

GATEWAY = Entity(id="payments-gateway", name="Payments Gateway",
                 aliases=("pmt-gw", "the gateway"), kind="system")


def _service(root, project, team="platform"):
    return MemoryService(LocalStore(root, project=project, team=team),
                         actor="t", project=project, team=team)


@pytest.fixture
def graph_data(tmp_path):
    payments = _service(tmp_path, "payments")
    search = _service(tmp_path, "search-svc", team="discovery")
    payments.set_ontology(Ontology(entities=[GATEWAY]))
    payments.create("/gotchas/timeout.md", "# pmt-gw drops connections\n\nRaise it.",
                    category="gotcha")
    payments.create("/secret/zeus2.md", "# the gateway rewrite is unannounced\n\nx",
                    visibility=Visibility.PRIVATE)
    search.create("/gotchas/crawler.md", "# Crawler calls the gateway\n\nBudget 25s.",
                  category="gotcha")
    return search.graph()


class TestSelfContained:
    """It must render inside a network that can reach nothing but this app."""

    def test_the_page_loads_nothing_from_the_internet(self):
        external = re.findall(r"""(?:src|href)\s*=\s*["'](https?:)?//[^"']+""", PAGE)
        assert external == [], f"page would fetch remote assets: {external}"

    def test_the_only_fetch_is_same_origin_relative(self):
        fetches = re.findall(r"fetch\(([^)]*)\)", PAGE)
        assert fetches, "the page must fetch its data"
        for call in fetches:
            assert "http" not in call.lower(), f"non-relative fetch: {call}"
            assert '"graph"' in call or "'graph'" in call

    def test_no_build_step_is_implied(self):
        for token in ("import ", "require(", "export default", "from 'react'"):
            assert token not in PAGE, f"page uses {token!r}; it must run as-is"

    def test_the_function_key_is_read_from_the_url_not_embedded(self):
        assert 'get("code")' in PAGE
        assert "x-functions-key" not in PAGE, "a key must never be baked into the page"

    def test_untrusted_values_are_escaped_before_being_written_as_html(self):
        """Memory titles and paths are user content rendered into innerHTML."""
        assert "function esc(" in PAGE
        panel = PAGE.split("function select(")[1]
        for field in ("m.title", "m.path", "m.project", "m.category", "node.label"):
            assert f"esc({field})" in panel, f"{field} reaches innerHTML unescaped"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
class TestRendersUnderNode:
    """Drive the real page script over real graph data."""

    def _run(self, graph_data, driver: str) -> str:
        script = re.search(r"<script>(.*?)</script>", PAGE, re.S).group(1)
        harness = """
        const store = {};
        class El {
          constructor(t){ this.tag=t; this.children=[]; this.attrs={};
                          this._html=""; this.textContent=""; }
          setAttribute(k,v){
            if (v === undefined || v === null ||
                (typeof v === "number" && !Number.isFinite(v)))
              throw new Error("bad attribute " + k + "=" + v);
            this.attrs[k]=v;
          }
          appendChild(c){ this.children.push(c); return c; }
          addEventListener(){}
          set innerHTML(v){ this._html=v; } get innerHTML(){ return this._html; }
          get clientWidth(){ return 900; } get clientHeight(){ return 600; }
        }
        global.document = {
          createElementNS:(ns,t)=>new El(t),
          getElementById:(id)=>store[id]||(store[id]=new El("div")),
          querySelector:()=>new El("div"),
        };
        global.location = { search: "" };
        global.URLSearchParams = class { constructor(){} get(){ return null; } };
        global.fetch = () => ({ then(){ return this; }, catch(){ return this; } });
        """
        body = harness + script + driver.replace("__DATA__", json.dumps(graph_data))
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(body)
            path = f.name
        result = subprocess.run(["node", path], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr[:1500]
        return result.stdout

    def test_every_node_gets_finite_geometry(self, graph_data):
        """The force simulation divides by distance; a coincident pair would
        produce NaN coordinates and an invisible, silently broken graph."""
        out = self._run(graph_data, """
        render(__DATA__);
        const circles = store["svg"].children[0].children
          .filter(c => c.tag === "g").flatMap(g => g.children)
          .filter(c => c.tag === "circle");
        if (!circles.length) throw new Error("nothing rendered");
        console.log("circles=" + circles.length);
        """)
        assert "circles=3" in out  # 1 entity + 2 projects

    def test_the_panel_shows_the_memories_and_never_a_hidden_one(self, graph_data):
        node = next(n for n in graph_data["nodes"] if n["id"] == "entity:payments-gateway")
        out = self._run(graph_data, f"""
        render(__DATA__);
        select({json.dumps(node)}, __DATA__);
        const html = store["panel"].innerHTML;
        if (!html.includes("Payments Gateway")) throw new Error("no entity name");
        if (!html.includes("payments")) throw new Error("no owning project");
        if (html.includes("zeus2")) throw new Error("LEAK: private memory rendered");
        console.log("panel=ok");
        """)
        assert "panel=ok" in out

    def test_an_empty_graph_explains_itself_instead_of_drawing_nothing(self):
        out = self._run(
            {"nodes": [], "edges": [], "memories": {}, "stats": {"vocabulary_size": 0}},
            """
            render(__DATA__);
            const html = store["panel"].innerHTML;
            if (!html.includes("ontology add")) throw new Error("no guidance shown");
            console.log("empty=ok");
            """,
        )
        assert "empty=ok" in out
