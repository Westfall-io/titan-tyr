class TestTemplates:
    async def test_software_template(self, client):
        r = await client.get("/templates/software")
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert r.text.startswith("# <software-name>")

    async def test_contract_template(self, client):
        r = await client.get("/templates/contract")
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert "Provider obligations" in r.text
