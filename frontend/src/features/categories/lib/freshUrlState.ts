// URL convention:
//   absent → fresh = true (default ON for the new UI)
//   ?fresh=0 → false
//   ?fresh=1 → true
export function readFresh(params: URLSearchParams): boolean {
  const raw = params.get('fresh');
  if (raw == null) return true;
  return raw !== '0';
}

export function writeFresh(params: URLSearchParams, fresh: boolean): URLSearchParams {
  const next = new URLSearchParams(params);
  if (fresh) next.delete('fresh');
  else next.set('fresh', '0');
  return next;
}
