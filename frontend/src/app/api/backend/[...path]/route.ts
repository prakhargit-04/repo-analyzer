import { buildBackendRequest, responseHeaders, validateBackendPath } from "@/lib/proxy";

export const dynamic = "force-dynamic";

async function proxy(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const baseUrl = process.env.BACKEND_URL;
  if (!baseUrl) {
    return Response.json({ detail: "Backend proxy is not configured." }, { status: 502 });
  }
  if (!validateBackendPath(path)) {
    return Response.json({ detail: "Invalid API path." }, { status: 400 });
  }

  try {
    const upstream = await fetch(
      buildBackendRequest(request, path, baseUrl, process.env.BACKEND_API_KEY)
    );
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders(upstream.headers),
    });
  } catch {
    return Response.json({ detail: "Backend service is unavailable." }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
