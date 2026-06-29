# Devin / cloud agents → Company Brain (REST)

Cloud agents (Devin, etc.) run on a remote VM and can't spawn the local
`brain-mcp` stdio connector, so connect them over the REST API.

- Base URL: `https://YOUR_BRAIN_HOST`
- Auth: `Authorization: Bearer <YOUR_API_KEY>`  (use a key dedicated to the agent)
- TLS: with a self-signed/IP cert, the client must skip verification (`curl -k`).
  A real domain + Let's Encrypt cert avoids this.

```bash
# capture a memory
curl -X POST https://YOUR_BRAIN_HOST/ingest \
  -H "Authorization: Bearer <YOUR_API_KEY>" -H "Content-Type: application/json" \
  -d '{"text":"User: ...\n\nAssistant: ...","title":"chat","source":"devin","project":"default"}'

# search
curl -X POST https://YOUR_BRAIN_HOST/search \
  -H "Authorization: Bearer <YOUR_API_KEY>" -H "Content-Type: application/json" \
  -d '{"query":"what did we decide about X","limit":5}'
```

Alternatively, install the connector inside the agent's VM per session:
```bash
pip install -e .   # from this repo, provides `brain-mcp`
BRAIN_URL=https://YOUR_BRAIN_HOST BRAIN_API_KEY=<YOUR_API_KEY> \
  BRAIN_AGENT=devin BRAIN_PROJECT=default brain-mcp
```
