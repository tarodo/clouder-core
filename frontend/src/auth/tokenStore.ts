let token: string | null = null;

export const tokenStore = {
  get(): string | null {
    return token;
  },
  set(value: string | null): void {
    token = value;
  },
};
