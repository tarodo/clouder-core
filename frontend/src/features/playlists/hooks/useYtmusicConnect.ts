import { useMutation } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface DeviceCodeResponse {
  device_code: string;
  user_code: string;
  verification_url: string;
  interval: number;
  expires_in: number;
}

export interface PollResponse {
  status?: 'authorization_pending' | 'slow_down';
  connected?: boolean;
}

export function useRequestDeviceCode() {
  return useMutation<DeviceCodeResponse, Error, void>({
    mutationFn: () => api<DeviceCodeResponse>('/auth/ytmusic/device-code', { method: 'POST' }),
  });
}

export function usePollYtmusic() {
  return useMutation<PollResponse, Error, { deviceCode: string }>({
    mutationFn: ({ deviceCode }) =>
      api<PollResponse>('/auth/ytmusic/poll', {
        method: 'POST',
        body: JSON.stringify({ device_code: deviceCode }),
      }),
  });
}
