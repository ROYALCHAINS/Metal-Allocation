/**
 * client.js — shared fetch wrapper. Replaces every `google.script.run.<fn>()`
 * call site from the legacy client modules with a real HTTP request against
 * the FastAPI backend.
 *
 * Auth: the backend expects a Google ID token as a Bearer header (see
 * rmas/routers/deps.py). auth.js owns obtaining that token via Google
 * Identity Services and calls setAuthToken() once signed in.
 */

const API_BASE = window.RMAS_API_BASE || '/api';

let authToken = null;

export function setAuthToken(token) {
  authToken = token;
}

async function request(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (authToken) headers.Authorization = `Bearer ${authToken}`;

  const res = await fetch(API_BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    data = null;
  }

  if (!res.ok) {
    const err = new Error((data && data.message) || `Request failed (${res.status})`);
    err.code = data && data.code;
    err.status = res.status;
    throw err;
  }
  return data;
}

export const get = (path) => request('GET', path);
export const post = (path, body) => request('POST', path, body);
