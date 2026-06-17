const ORIGIN_API = 'http://39.107.137.91/a-share-etf/api';

export async function onRequest(context) {
  const url = new URL(context.request.url);
  const path = Array.isArray(context.params.path) ? context.params.path.join('/') : (context.params.path || '');
  const upstream = `${ORIGIN_API}/${path}${url.search}`;
  const response = await fetch(upstream, {
    method: context.request.method,
    headers: {
      'Accept': context.request.headers.get('Accept') || 'application/json',
      'User-Agent': 'Mozilla/5.0 (compatible; AShareETFSentinelPagesProxy/1.0)',
    },
    body: ['GET', 'HEAD'].includes(context.request.method) ? undefined : context.request.body,
  });
  const headers = new Headers(response.headers);
  headers.set('Access-Control-Allow-Origin', '*');
  headers.set('Cache-Control', context.request.method === 'GET' ? 'public, max-age=60' : 'no-store');
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

export const onRequestGet = onRequest;
export const onRequestHead = onRequest;
export const onRequestPost = onRequest;
export function onRequestOptions() {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, HEAD, POST, OPTIONS',
      'Access-Control-Allow-Headers': '*',
      'Access-Control-Max-Age': '86400',
    },
  });
}
