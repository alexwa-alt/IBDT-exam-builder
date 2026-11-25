// Vault: unlocks the encrypted question bank in the browser (Web Crypto API).
// Matches scripts/encrypt_site.py: PBKDF2-HMAC-SHA256 key, AES-256-GCM files stored as nonce + ciphertext.
// All file access goes through Vault.json / Vault.bytes / Vault.imageURL, which decrypt on demand.
'use strict';

const Vault = (() => {
  const STORE = 'dt-bank-key';
  const CHECK_TEXT = 'dt-bank password check';
  let lock = null, key = null, index = null;
  const cache = new Map();      // real name -> Promise<Uint8Array>
  const urls = new Map();       // real name -> Promise<blob: URL>

  const fromB64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const toB64 = b => btoa(String.fromCharCode(...new Uint8Array(b)));
  const store = {
    get() { try { return localStorage.getItem(STORE); } catch (e) { return null; } },
    set(v) { try { localStorage.setItem(STORE, v); } catch (e) { /* private mode: not remembered */ } },
    clear() { try { localStorage.removeItem(STORE); } catch (e) { /* ignore */ } },
  };

  async function loadLock() {
    if (lock) return lock;
    const r = await fetch('data/lock.json', { cache: 'no-store' });
    if (!r.ok) throw new Error('The site has not been built yet (data/lock.json is missing).');
    lock = await r.json();
    if (lock.version !== 1) throw new Error('This page is out of date. Please reload it.');
    return lock;
  }

  async function decrypt(k, bytes) {
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: bytes.slice(0, 12) }, k, bytes.slice(12));
    return new Uint8Array(plain);
  }

  // True if the key decrypts the check value (wrong password -> AES-GCM refuses to decrypt).
  async function works(k) {
    try {
      const text = new TextDecoder().decode(await decrypt(k, fromB64(lock.check)));
      return text === CHECK_TEXT;
    } catch (e) { return false; }
  }

  async function open(k) {
    key = k;
    const r = await fetch('data/enc/' + lock.index);
    if (!r.ok) throw new Error('Could not load the question bank. Please reload the page.');
    index = JSON.parse(new TextDecoder().decode(await decrypt(key, new Uint8Array(await r.arrayBuffer()))));
  }

  return {
    get supported() { return !!(window.crypto && crypto.subtle); },

    // Try the key remembered on this device. Returns true if it still works.
    async resume() {
      await loadLock();
      const saved = store.get();
      if (!saved) return false;
      try {
        const k = await crypto.subtle.importKey('raw', fromB64(saved), 'AES-GCM', true, ['decrypt']);
        if (await works(k)) { await open(k); return true; }
      } catch (e) { /* fall through */ }
      store.clear();              // password changed since this device logged in
      return false;
    },

    // Derive the key from a typed password. Returns true if the password is right.
    async unlock(password, remember) {
      await loadLock();
      const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false,
                                                 ['deriveKey']);
      const k = await crypto.subtle.deriveKey(
        { name: 'PBKDF2', salt: fromB64(lock.salt), iterations: lock.iterations, hash: 'SHA-256' },
        base, { name: 'AES-GCM', length: 256 }, true, ['decrypt']);
      if (!(await works(k))) return false;
      await open(k);
      if (remember) store.set(toB64(await crypto.subtle.exportKey('raw', k)));
      else store.clear();
      return true;
    },

    logout() {
      store.clear();
      key = null; index = null;
      urls.forEach(p => p.then(u => URL.revokeObjectURL(u)).catch(() => {}));
      urls.clear(); cache.clear();
    },

    get built() { return index && index.built; },

    // Decrypted bytes of a file, by its real name ("questions.json", "images/x_q1.png").
    bytes(name) {
      if (!cache.has(name)) {
        const p = (async () => {
          const file = index && index.files[name];
          if (!file) throw new Error('Not in the bank: ' + name);
          const r = await fetch('data/enc/' + file);
          if (!r.ok) throw new Error('Could not load ' + name);
          return decrypt(key, new Uint8Array(await r.arrayBuffer()));
        })();
        p.catch(() => cache.delete(name));     // allow a retry after a network error
        cache.set(name, p);
      }
      return cache.get(name);
    },

    async json(name) { return JSON.parse(new TextDecoder().decode(await this.bytes(name))); },

    // A blob: URL (temporary in-memory address) for an image, for <img src>.
    imageURL(name) {
      if (!urls.has(name)) {
        const p = this.bytes(name).then(b => URL.createObjectURL(new Blob([b], { type: 'image/png' })));
        p.catch(() => urls.delete(name));
        urls.set(name, p);
      }
      return urls.get(name);
    },
  };
})();
