export class ApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
    readonly correlationId?: string,
    readonly raw?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  static async from(res: Response): Promise<ApiError> {
    const correlationId = res.headers.get('x-correlation-id') ?? undefined;
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // body is not JSON (HTML, empty, binary)
    }

    if (body && typeof body === 'object' && 'error_code' in body) {
      const b = body as { error_code: string; message?: string; correlation_id?: string };
      return new ApiError(
        b.error_code,
        res.status,
        b.message ?? res.statusText,
        b.correlation_id ?? correlationId,
        body,
      );
    }

    if (
      res.status === 503 &&
      body &&
      typeof body === 'object' &&
      'message' in body &&
      (body as { message: unknown }).message === 'Service Unavailable'
    ) {
      return new ApiError('cold_start', 503, 'Backend warming up', correlationId, body);
    }

    return new ApiError('unknown', res.status, res.statusText || 'Unknown error', correlationId, body);
  }
}
