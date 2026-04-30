import { describe, it, expect } from 'vitest';
import { ApiError } from '../error';

function makeRes(body: unknown, status: number, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

describe('ApiError.from', () => {
  it('parses domain error envelope', async () => {
    const res = makeRes(
      { error_code: 'validation_error', message: 'bad input', correlation_id: 'cid-1' },
      400,
    );
    const err = await ApiError.from(res);
    expect(err.code).toBe('validation_error');
    expect(err.status).toBe(400);
    expect(err.message).toBe('bad input');
    expect(err.correlationId).toBe('cid-1');
  });

  it('maps API Gateway 503 cold-start to code=cold_start', async () => {
    const res = makeRes({ message: 'Service Unavailable' }, 503);
    const err = await ApiError.from(res);
    expect(err.code).toBe('cold_start');
    expect(err.status).toBe(503);
  });

  it('falls back to unknown for unparseable bodies', async () => {
    const res = new Response('<!doctype html>', {
      status: 502,
      headers: { 'content-type': 'text/html' },
    });
    const err = await ApiError.from(res);
    expect(err.code).toBe('unknown');
    expect(err.status).toBe(502);
  });

  it('reads x-correlation-id from response headers when body lacks it', async () => {
    const res = makeRes({ message: 'Service Unavailable' }, 503, {
      'x-correlation-id': 'cid-from-header',
    });
    const err = await ApiError.from(res);
    expect(err.correlationId).toBe('cid-from-header');
  });
});
