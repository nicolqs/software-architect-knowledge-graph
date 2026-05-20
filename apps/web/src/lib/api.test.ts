import { describe, expect, it } from 'vitest';
import { api } from './api';

describe('api client', () => {
  it('exposes all agent endpoints + graph + decisions', () => {
    expect(api).toMatchObject({
      health: expect.any(Function),
      repos: expect.any(Function),
      subgraph: expect.any(Function),
      echo: expect.any(Function),
      tickets: expect.any(Function),
      architect: expect.any(Function),
      reviewer: expect.any(Function),
      refactor: expect.any(Function),
      decisions: expect.any(Function),
      reviewDecision: expect.any(Function),
    });
  });
});
