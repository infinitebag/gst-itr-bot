/**
 * GST/ITR Bot – Cloudflare Worker Webhook Proxy
 *
 * Forwards all requests to the cloudflared quick-tunnel origin.
 * The TUNNEL_ORIGIN env var holds the current trycloudflare.com URL.
 *
 * To update the tunnel URL without redeploying:
 *   npx wrangler secret put TUNNEL_ORIGIN
 *   (or change it in the Cloudflare dashboard under Worker Settings > Variables)
 *
 * Once you have a custom domain + named tunnel, replace TUNNEL_ORIGIN
 * with your permanent hostname (e.g. https://api.yourdomain.com).
 */
export default {
  async fetch(request, env) {
    const origin = env.TUNNEL_ORIGIN;
    if (!origin) {
      return new Response("TUNNEL_ORIGIN not configured", { status: 502 });
    }

    const url = new URL(request.url);
    const targetUrl = origin + url.pathname + url.search;

    // Clone the request, forwarding method, headers, and body
    const proxyRequest = new Request(targetUrl, {
      method: request.method,
      headers: request.headers,
      body: request.method !== "GET" && request.method !== "HEAD"
        ? request.body
        : undefined,
      redirect: "follow",
    });

    try {
      const response = await fetch(proxyRequest);

      // Return response with CORS-safe headers
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    } catch (err) {
      return new Response(`Proxy error: ${err.message}`, { status: 502 });
    }
  },
};
