# Root-path Worker

Serves `index.html` at `https://kellblog.thisisgrant.com/`.

Deploy (needs `CLOUDFLARE_API_TOKEN` with Workers Scripts + Workers Routes edit):

    cd infra/home-worker && npx wrangler deploy

The Cloudflare account ID is not stored here; wrangler finds it from the token.
