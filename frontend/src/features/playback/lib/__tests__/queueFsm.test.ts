import { describe, it, expect } from 'vitest';
import { transition } from '../queueFsm';

describe('queueFsm.transition', () => {
  it('idle → loading on PLAY_REQUESTED', () => {
    expect(transition('idle', { type: 'PLAY_REQUESTED' })).toBe('loading');
  });
  it('loading → playing on SDK_PLAYING', () => {
    expect(transition('loading', { type: 'SDK_PLAYING' })).toBe('playing');
  });
  it('playing → paused on PAUSE', () => {
    expect(transition('playing', { type: 'PAUSE' })).toBe('paused');
  });
  it('paused → playing on RESUME', () => {
    expect(transition('paused', { type: 'RESUME' })).toBe('playing');
  });
  it('any non-error → ended on END', () => {
    expect(transition('playing', { type: 'END' })).toBe('ended');
    expect(transition('paused', { type: 'END' })).toBe('ended');
  });
  it('any → error on SDK_ERROR', () => {
    expect(transition('playing', { type: 'SDK_ERROR' })).toBe('error');
    expect(transition('idle', { type: 'SDK_ERROR' })).toBe('error');
  });
  it('error → loading on RETRY', () => {
    expect(transition('error', { type: 'RETRY' })).toBe('loading');
  });
  it('any → idle on CLEAR', () => {
    expect(transition('playing', { type: 'CLEAR' })).toBe('idle');
    expect(transition('error', { type: 'CLEAR' })).toBe('idle');
  });
  it('returns same status on unknown event', () => {
    expect(transition('playing', { type: 'PAUSE' as never })).toBe('paused');
    expect(transition('idle', { type: '__unknown__' as never })).toBe('idle');
  });
});
