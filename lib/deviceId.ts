export function getDeviceId(): string {
  if (typeof window === 'undefined') return '';
  let id = localStorage.getItem('lp_device_id');
  if (!id) { id = (crypto.randomUUID?.() ?? String(Date.now()) + Math.random()); localStorage.setItem('lp_device_id', id); }
  return id;
}
