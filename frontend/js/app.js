/**
 * Wedding Photo Platform – Frontend Application
 *
 * Handles:
 *  - Cognito authentication (sign-in / register / confirm)
 *  - Direct S3 photo/video uploads via presigned PUT URLs
 *  - Gallery browsing with pagination
 *  - Selfie-based photo search
 *  - Couple photo gallery
 *  - Lightbox viewer with download
 */

'use strict';

/* ── Configuration ─────────────────────────────────────────────────────────
   These values are injected at deploy time (e.g. via a CI/CD step that
   generates a config.js or replaces the placeholders below).
   ──────────────────────────────────────────────────────────────────────── */
const CONFIG = {
  apiEndpoint:    window.WEDDING_API_ENDPOINT    || 'https://YOUR_API_GATEWAY_URL/dev',
  userPoolId:     window.WEDDING_USER_POOL_ID    || 'us-east-1_EXAMPLE',
  userPoolClient: window.WEDDING_USER_POOL_CLIENT || 'EXAMPLE_CLIENT_ID',
  region:         window.WEDDING_AWS_REGION       || 'us-east-1',
};

/* ── Cognito SRP Auth (Lightweight, no AWS Amplify dependency) ─────────── */
class CognitoAuth {
  constructor({ userPoolId, clientId, region }) {
    this._poolId  = userPoolId;
    this._client  = clientId;
    this._region  = region;
    this._baseUrl = `https://cognito-idp.${region}.amazonaws.com/`;
  }

  async _call(target, payload) {
    const res = await fetch(this._baseUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': target,
      },
      body: JSON.stringify(payload),
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.message || json.__type || 'Cognito error');
    return json;
  }

  async signIn(email, password) {
    const data = await this._call('AWSCognitoIdentityProviderService.InitiateAuth', {
      AuthFlow: 'USER_PASSWORD_AUTH',
      ClientId: this._client,
      AuthParameters: { USERNAME: email, PASSWORD: password },
    });
    return data.AuthenticationResult;
  }

  async signUp(email, password, givenName, familyName) {
    const userAttributes = [{ Name: 'email', Value: email }];
    if (givenName)   userAttributes.push({ Name: 'given_name',  Value: givenName });
    if (familyName)  userAttributes.push({ Name: 'family_name', Value: familyName });
    return this._call('AWSCognitoIdentityProviderService.SignUp', {
      ClientId: this._client,
      Username: email,
      Password: password,
      UserAttributes: userAttributes,
    });
  }

  async confirmSignUp(email, code) {
    return this._call('AWSCognitoIdentityProviderService.ConfirmSignUp', {
      ClientId: this._client,
      Username: email,
      ConfirmationCode: code,
    });
  }
}

/* ── State ──────────────────────────────────────────────────────────────── */
const state = {
  idToken: localStorage.getItem('wedding_id_token') || null,
  userEmail: localStorage.getItem('wedding_user_email') || null,
  galleryCursors: [null],   // stack of cursors for back-navigation
  galleryPage: 0,
  coupleCursors: [null],
  couplePage: 0,
  lightboxItems: [],
  lightboxIndex: 0,
  pendingRegEmail: null,
};

const auth = new CognitoAuth({
  userPoolId: CONFIG.userPoolId,
  clientId:   CONFIG.userPoolClient,
  region:     CONFIG.region,
});

/* ── Helpers ────────────────────────────────────────────────────────────── */
function apiHeaders() {
  const h = { 'Content-Type': 'application/json' };
  if (state.idToken) h['Authorization'] = state.idToken;
  return h;
}

async function apiFetch(path, options = {}) {
  const url = `${CONFIG.apiEndpoint}${path}`;
  const res = await fetch(url, { ...options, headers: { ...apiHeaders(), ...(options.headers || {}) } });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4200);
}

function setLoading(elementId, loading) {
  const el = document.getElementById(elementId);
  if (el) el.style.opacity = loading ? '0.5' : '1';
}

function formatDate(iso) {
  if (!iso) return '';
  try { return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); }
  catch { return ''; }
}

/* ── Authentication UI ──────────────────────────────────────────────────── */
function updateAuthUI() {
  const authBtn  = document.getElementById('auth-btn');
  const userLabel = document.getElementById('user-label');
  if (state.idToken && state.userEmail) {
    authBtn.textContent = 'Sign Out';
    userLabel.textContent = state.userEmail;
    userLabel.hidden = false;
  } else {
    authBtn.textContent = 'Sign In';
    userLabel.hidden = true;
  }
}

function openAuthModal() {
  document.getElementById('auth-modal').hidden = false;
}
function closeAuthModal() {
  document.getElementById('auth-modal').hidden = true;
}

function showAuthTab(tab) {
  document.getElementById('signin-form').hidden   = tab !== 'signin';
  document.getElementById('register-form').hidden = tab !== 'register';
  document.getElementById('confirm-form').hidden  = tab !== 'confirm';
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab);
  });
}

/* ── Navigation ──────────────────────────────────────────────────────────── */
function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.add('hidden'));
  document.getElementById(`section-${name}`)?.classList.remove('hidden');
  document.querySelectorAll('.nav-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.section === name);
    b.setAttribute('aria-current', b.dataset.section === name ? 'page' : 'false');
  });

  if (name === 'gallery' && document.getElementById('gallery-grid').children.length <= 1) {
    loadGallery();
  }
  if (name === 'couple' && document.getElementById('couple-grid').children.length <= 1) {
    loadCouplePhotos();
  }
}

/* ── Gallery ────────────────────────────────────────────────────────────── */
async function loadGallery(cursor = null) {
  const grid = document.getElementById('gallery-grid');
  grid.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Loading photos…</p></div>`;

  const params = new URLSearchParams({ limit: '24' });
  if (cursor) params.set('cursor', cursor);

  try {
    const data = await apiFetch(`/media?${params}`);
    state.lightboxItems = data.media || [];
    renderPhotoGrid(grid, data.media || [], 'gallery');

    const nextBtn = document.getElementById('gallery-next-btn');
    const prevBtn = document.getElementById('gallery-prev-btn');
    nextBtn.disabled = !data.next_cursor;
    prevBtn.disabled = state.galleryPage === 0;

    if (data.next_cursor) {
      nextBtn.onclick = () => {
        state.galleryCursors.push(cursor);
        state.galleryPage++;
        loadGallery(data.next_cursor);
      };
    }
    prevBtn.onclick = () => {
      if (state.galleryPage > 0) {
        state.galleryPage--;
        const prev = state.galleryCursors.pop();
        loadGallery(prev);
      }
    };
  } catch (err) {
    grid.innerHTML = `<div class="empty-state"><span>📷</span><p>Could not load photos. ${err.message}</p></div>`;
  }
}

/* ── Couple Photos ────────────────────────────────────────────────────────── */
async function loadCouplePhotos(cursor = null) {
  const grid = document.getElementById('couple-grid');
  grid.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Loading…</p></div>`;

  const params = new URLSearchParams({ limit: '24' });
  if (cursor) params.set('cursor', cursor);

  try {
    const data = await apiFetch(`/couple-photos?${params}`);
    renderPhotoGrid(grid, data.photos || [], 'couple');

    const nextBtn = document.getElementById('couple-next-btn');
    const prevBtn = document.getElementById('couple-prev-btn');
    nextBtn.disabled = !data.next_cursor;
    prevBtn.disabled = state.couplePage === 0;

    if (data.next_cursor) {
      nextBtn.onclick = () => {
        state.coupleCursors.push(cursor);
        state.couplePage++;
        loadCouplePhotos(data.next_cursor);
      };
    }
    prevBtn.onclick = () => {
      if (state.couplePage > 0) {
        state.couplePage--;
        const prev = state.coupleCursors.pop();
        loadCouplePhotos(prev);
      }
    };
  } catch (err) {
    grid.innerHTML = `<div class="empty-state"><span>💑</span><p>Could not load couple photos. ${err.message}</p></div>`;
  }
}

/* ── Render Photo Grid ────────────────────────────────────────────────────── */
function renderPhotoGrid(grid, items, context) {
  grid.innerHTML = '';

  if (!items.length) {
    grid.innerHTML = `<div class="empty-state"><span>📷</span><p>No photos here yet. Be the first to upload!</p></div>`;
    return;
  }

  items.forEach((item, idx) => {
    const isVideo = item.content_type && item.content_type.startsWith('video/');
    const card = document.createElement('div');
    card.className = `photo-card${isVideo ? ' is-video' : ''}`;
    card.setAttribute('role', 'listitem');
    card.tabIndex = 0;
    card.setAttribute('aria-label', `Photo uploaded by ${item.uploaded_by || 'guest'} on ${formatDate(item.upload_timestamp)}`);

    if (isVideo) {
      const thumb = document.createElement('div');
      thumb.style.cssText = 'width:100%;height:100%;background:#222;display:flex;align-items:center;justify-content:center;';
      card.appendChild(thumb);
    } else {
      const img = document.createElement('img');
      img.src = item.download_url;
      img.alt = `Wedding photo uploaded on ${formatDate(item.upload_timestamp)}`;
      img.loading = 'lazy';
      card.appendChild(img);
    }

    const overlay = document.createElement('div');
    overlay.className = 'photo-overlay';

    if (item.is_couple_photo) {
      const badge = document.createElement('span');
      badge.className = 'couple-badge';
      badge.textContent = '💍 Couple';
      overlay.appendChild(badge);
    }

    const dlBtn = document.createElement('a');
    dlBtn.className = 'photo-download-btn';
    dlBtn.href = item.download_url;
    dlBtn.download = '';
    dlBtn.textContent = '⬇ Save';
    dlBtn.setAttribute('aria-label', 'Download this photo');
    dlBtn.addEventListener('click', e => e.stopPropagation());
    overlay.appendChild(dlBtn);

    card.appendChild(overlay);

    card.addEventListener('click', () => openLightbox(items, idx));
    card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') openLightbox(items, idx); });

    grid.appendChild(card);
  });
}

/* ── Lightbox ─────────────────────────────────────────────────────────────── */
function openLightbox(items, index) {
  state.lightboxItems = items;
  state.lightboxIndex = index;
  renderLightboxItem();
  document.getElementById('lightbox').hidden = false;
  document.body.style.overflow = 'hidden';
}

function closeLightbox() {
  document.getElementById('lightbox').hidden = true;
  document.body.style.overflow = '';
  const video = document.getElementById('lightbox-video');
  video.pause();
}

function renderLightboxItem() {
  const item = state.lightboxItems[state.lightboxIndex];
  if (!item) return;
  const img   = document.getElementById('lightbox-img');
  const video = document.getElementById('lightbox-video');
  const dlBtn = document.getElementById('lightbox-download');
  const isVideo = item.content_type && item.content_type.startsWith('video/');

  if (isVideo) {
    video.src = item.download_url;
    video.hidden = false;
    img.hidden = true;
  } else {
    img.src = item.download_url;
    img.hidden = false;
    video.hidden = true;
    video.pause();
  }

  dlBtn.href = item.download_url;
  document.getElementById('lightbox-prev').disabled = state.lightboxIndex === 0;
  document.getElementById('lightbox-next').disabled = state.lightboxIndex === state.lightboxItems.length - 1;
}

/* ── Upload ────────────────────────────────────────────────────────────────── */
const ALLOWED_UPLOAD_TYPES = new Set([
  'image/jpeg','image/jpg','image/png','image/webp','image/heic','image/heif',
  'video/mp4','video/quicktime','video/x-msvideo','video/mpeg','video/webm',
]);
const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100 MB

function addFilesToQueue(files) {
  const queue = document.getElementById('upload-queue');
  let added = 0;
  Array.from(files).forEach(file => {
    if (!ALLOWED_UPLOAD_TYPES.has(file.type.toLowerCase())) {
      showToast(`Unsupported file type: ${file.name}`, 'error');
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      showToast(`File too large (max 100 MB): ${file.name}`, 'error');
      return;
    }

    const item = document.createElement('div');
    item.className = 'upload-item';
    item.dataset.filename = file.name;

    const nameEl = document.createElement('span');
    nameEl.className = 'upload-item-name';
    nameEl.textContent = file.name;

    const progressWrap = document.createElement('div');
    progressWrap.className = 'upload-progress';
    const progressBar = document.createElement('div');
    progressBar.className = 'upload-progress-bar';
    progressWrap.appendChild(progressBar);

    const statusEl = document.createElement('span');
    statusEl.className = 'upload-item-status pending';
    statusEl.textContent = 'Pending';

    item.appendChild(nameEl);
    item.appendChild(progressWrap);
    item.appendChild(statusEl);
    item.file = file;
    item.progressBar = progressBar;
    item.statusEl = statusEl;

    queue.appendChild(item);
    added++;
  });

  if (added > 0) {
    document.getElementById('upload-btn').disabled = false;
  }
}

async function uploadFile(queueItem) {
  const file = queueItem.file;
  queueItem.statusEl.className = 'upload-item-status uploading';
  queueItem.statusEl.textContent = 'Uploading…';
  queueItem.progressBar.style.width = '10%';

  try {
    // 1. Get presigned URL from backend
    const urlData = await apiFetch('/upload-url', {
      method: 'POST',
      body: JSON.stringify({ file_name: file.name, content_type: file.type }),
    });

    queueItem.progressBar.style.width = '30%';

    // 2. Upload directly to S3
    const uploadRes = await fetch(urlData.upload_url, {
      method: 'PUT',
      body: file,
      headers: { 'Content-Type': file.type },
    });

    if (!uploadRes.ok) throw new Error(`S3 upload failed: ${uploadRes.status}`);

    queueItem.progressBar.style.width = '100%';
    queueItem.statusEl.className = 'upload-item-status done';
    queueItem.statusEl.textContent = '✓ Done';
    return true;
  } catch (err) {
    queueItem.progressBar.style.width = '100%';
    queueItem.progressBar.style.background = 'var(--color-error)';
    queueItem.statusEl.className = 'upload-item-status error';
    queueItem.statusEl.textContent = '✕ Failed';
    showToast(`Failed to upload ${file.name}: ${err.message}`, 'error');
    return false;
  }
}

/* ── Selfie Search ──────────────────────────────────────────────────────────── */
async function runSelfieSearch() {
  const fileInput = document.getElementById('selfie-input');
  if (!fileInput.files.length) return;

  const file = fileInput.files[0];
  const resultsEl = document.getElementById('search-results');
  const searchBtn = document.getElementById('selfie-search-btn');

  searchBtn.disabled = true;
  searchBtn.textContent = 'Searching…';
  resultsEl.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Searching for your photos…</p></div>`;

  try {
    const arrayBuffer = await file.arrayBuffer();
    const base64 = btoa(String.fromCharCode(...new Uint8Array(arrayBuffer)));

    const data = await apiFetch('/search', {
      method: 'POST',
      body: JSON.stringify({ selfie_image: base64, content_type: file.type }),
    });

    resultsEl.innerHTML = '';

    if (!data.matched_photos || data.matched_photos.length === 0) {
      resultsEl.innerHTML = `<div class="empty-state" id="search-empty"><span>🔍</span><p>${data.message || 'No matching photos found. Make sure the couple has tagged your face!'}</p></div>`;
    } else {
      showToast(`Found ${data.total} photo(s) featuring you! 🎉`, 'success');
      const grid = document.createElement('div');
      grid.className = 'photo-grid';
      grid.setAttribute('role', 'list');
      resultsEl.appendChild(grid);
      renderPhotoGrid(grid, data.matched_photos, 'search');
    }
  } catch (err) {
    resultsEl.innerHTML = `<div class="empty-state"><span>⚠️</span><p>Search failed: ${err.message}</p></div>`;
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = 'Search My Photos';
  }
}

/* ── Event Wiring ────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {

  updateAuthUI();

  // ── Navigation
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => showSection(btn.dataset.section));
  });

  // Load gallery on initial render
  loadGallery();

  // ── Auth modal
  document.getElementById('auth-btn').addEventListener('click', () => {
    if (state.idToken) {
      // Sign out
      state.idToken = null;
      state.userEmail = null;
      localStorage.removeItem('wedding_id_token');
      localStorage.removeItem('wedding_user_email');
      updateAuthUI();
      showToast('Signed out.', 'info');
    } else {
      openAuthModal();
    }
  });

  document.getElementById('auth-modal-close').addEventListener('click', closeAuthModal);
  document.getElementById('auth-modal').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeAuthModal();
  });

  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => showAuthTab(btn.dataset.tab));
  });

  // Sign-in form
  document.getElementById('signin-form').addEventListener('submit', async e => {
    e.preventDefault();
    const email    = document.getElementById('signin-email').value.trim();
    const password = document.getElementById('signin-password').value;
    const errorEl  = document.getElementById('signin-error');
    errorEl.hidden = true;
    try {
      const result = await auth.signIn(email, password);
      state.idToken   = result.IdToken;
      state.userEmail = email;
      localStorage.setItem('wedding_id_token', result.IdToken);
      localStorage.setItem('wedding_user_email', email);
      updateAuthUI();
      closeAuthModal();
      showToast('Welcome back! 🎉', 'success');
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.hidden = false;
    }
  });

  // Register form
  document.getElementById('register-form').addEventListener('submit', async e => {
    e.preventDefault();
    const email      = document.getElementById('reg-email').value.trim();
    const password   = document.getElementById('reg-password').value;
    const givenName  = document.getElementById('reg-given-name').value.trim();
    const familyName = document.getElementById('reg-family-name').value.trim();
    const errorEl    = document.getElementById('reg-error');
    errorEl.hidden = true;
    try {
      await auth.signUp(email, password, givenName, familyName);
      state.pendingRegEmail = email;
      showAuthTab('confirm');
      showToast('Check your email for a verification code.', 'info');
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.hidden = false;
    }
  });

  // Confirm form
  document.getElementById('confirm-form').addEventListener('submit', async e => {
    e.preventDefault();
    const code    = document.getElementById('confirm-code').value.trim();
    const errorEl = document.getElementById('confirm-error');
    errorEl.hidden = true;
    try {
      await auth.confirmSignUp(state.pendingRegEmail, code);
      showToast('Email confirmed! You can now sign in.', 'success');
      showAuthTab('signin');
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.hidden = false;
    }
  });

  // ── Upload
  const dropZone  = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');

  dropZone.addEventListener('click', () => fileInput.click());
  dropZone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') fileInput.click(); });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) addFilesToQueue(fileInput.files);
    fileInput.value = '';
  });

  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    if (e.dataTransfer.files.length) addFilesToQueue(e.dataTransfer.files);
  });

  document.getElementById('upload-btn').addEventListener('click', async () => {
    if (!state.idToken) {
      showToast('Please sign in to upload photos.', 'error');
      openAuthModal();
      return;
    }

    const items = Array.from(document.getElementById('upload-queue').querySelectorAll('.upload-item'));
    const pending = items.filter(i => i.statusEl && i.statusEl.classList.contains('pending'));

    if (!pending.length) {
      showToast('No files to upload.', 'info');
      return;
    }

    for (const item of pending) {
      await uploadFile(item);
    }

    const doneCount = document.querySelectorAll('.upload-item-status.done').length;
    if (doneCount > 0) {
      showToast(`${doneCount} file(s) uploaded successfully! 📸`, 'success');
    }
  });

  // ── Selfie Search
  const selfieInput    = document.getElementById('selfie-input');
  const selfieChooseBtn = document.getElementById('selfie-choose-btn');
  const selfieSearchBtn = document.getElementById('selfie-search-btn');
  const selfiePreview   = document.getElementById('selfie-preview');
  const selfiePlaceholder = document.getElementById('selfie-placeholder');

  selfieChooseBtn.addEventListener('click', () => selfieInput.click());

  selfieInput.addEventListener('change', () => {
    if (!selfieInput.files.length) return;
    const file = selfieInput.files[0];
    const reader = new FileReader();
    reader.onload = e => {
      selfiePreview.src = e.target.result;
      selfiePreview.classList.remove('hidden');
      selfiePlaceholder.hidden = true;
      selfieSearchBtn.disabled = false;
    };
    reader.readAsDataURL(file);
  });

  selfieSearchBtn.addEventListener('click', runSelfieSearch);

  // ── Lightbox
  document.getElementById('lightbox-close').addEventListener('click', closeLightbox);
  document.getElementById('lightbox').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeLightbox();
  });

  document.getElementById('lightbox-prev').addEventListener('click', () => {
    if (state.lightboxIndex > 0) {
      state.lightboxIndex--;
      renderLightboxItem();
    }
  });

  document.getElementById('lightbox-next').addEventListener('click', () => {
    if (state.lightboxIndex < state.lightboxItems.length - 1) {
      state.lightboxIndex++;
      renderLightboxItem();
    }
  });

  document.addEventListener('keydown', e => {
    if (document.getElementById('lightbox').hidden) return;
    if (e.key === 'Escape')      closeLightbox();
    if (e.key === 'ArrowLeft')   document.getElementById('lightbox-prev').click();
    if (e.key === 'ArrowRight')  document.getElementById('lightbox-next').click();
  });

});
