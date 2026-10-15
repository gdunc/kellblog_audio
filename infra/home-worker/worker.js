// Serve the listening page at the bare root (https://kellblog.thisisgrant.com/).
// R2 custom domains have no index-document setting, so "/" would otherwise be a 404.
// The route in wrangler.toml matches only the exact root path; every other URL
// (feed, audio, artwork, /index.html) goes straight to R2 and never reaches this Worker.
export default {
  async fetch(request) {
    const url = new URL(request.url);
    url.pathname = "/index.html";
    return fetch(new Request(url, request));
  },
};
