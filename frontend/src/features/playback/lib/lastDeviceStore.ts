const KEY = 'clouder.last_device_id';

export const lastDeviceStore = {
  get(): string | null {
    try {
      return window.localStorage.getItem(KEY);
    } catch {
      return null;
    }
  },
  set(deviceId: string): void {
    try {
      window.localStorage.setItem(KEY, deviceId);
    } catch {
      // localStorage unavailable (Safari private, quota exceeded). No-op.
    }
  },
  clear(): void {
    try {
      window.localStorage.removeItem(KEY);
    } catch {
      // Same. No-op.
    }
  },
};
