const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers ?? {}),
    },
    ...options,
  })

  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || `Request failed: ${response.status}`)
  }

  return response.json()
}

export function startDialog(sessionId = null, userId = '') {
  return request('/interview/dialog/start', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, user_id: userId }),
  })
}

export function sendDialogAction(payload) {
  return request('/interview/dialog/actions', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function sendDialogText(payload) {
  return request('/interview/dialog/text', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getInterviewState(sessionId) {
  return request(`/interview/state/${sessionId}`)
}

export function getUserInfo(userId) {
  return request(`/interview/users/${userId}/userinfo`)
}

export function saveUserInfo(userId, payload) {
  return request(`/interview/users/${userId}/userinfo`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function getOnboardingGuide() {
  return request('/interview/onboarding/guide')
}
