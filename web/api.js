/* 作文分身 · 前端 API 客户端
 * 统一封装请求、错误提示、加载态。所有页面共用这一个文件。
 */
(function (global) {
  'use strict';

  const API_BASE = '';
  const UID_STUDENT = 'student_demo';
  const UID_TEACHER = 'teacher_demo';

  // 哪一端由页面决定：body[data-role]
  const role = document.body.getAttribute('data-role') || 'student';
  const uid = role === 'teacher' ? UID_TEACHER : UID_STUDENT;

  function qs(obj) {
    const parts = [];
    Object.keys(obj || {}).forEach(function (k) {
      if (obj[k] !== undefined && obj[k] !== null && obj[k] !== '') {
        parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(obj[k]));
      }
    });
    return parts.length ? '?' + parts.join('&') : '';
  }

  async function request(path, opts) {
    opts = opts || {};
    const headers = { 'X-User-Id': uid };
    let body;
    if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(opts.body);
    }
    const res = await fetch(API_BASE + path + qs(opts.query), {
      method: opts.method || (body ? 'POST' : 'GET'),
      headers: headers,
      body: body,
      credentials: 'same-origin'
    });

    let payload;
    try {
      payload = await res.json();
    } catch (e) {
      throw new Error('服务器返回了非 JSON 内容（HTTP ' + res.status + '）');
    }

    if (!res.ok || !payload.ok) {
      throw new Error((payload && payload.error) || ('HTTP ' + res.status));
    }
    return payload.data;
  }

  const api = {
    role: role,
    uid: uid,

    // ---------------- 学生端
    home: () => request('/api/student/home'),
    courses: () => request('/api/student/courses'),
    memory: () => request('/api/student/memory'),
    memoryFix: (id, content, confidence) =>
      request('/api/student/memory/fix', { body: { id: id, content: content, confidence: confidence } }),
    chat: (text) => request('/api/student/chat', { body: { text: text } }),
    suggestions: () => request('/api/student/suggestions'),
    flow: (courseId) => request('/api/student/flow', { query: { courseId: courseId } }),
    flowSubmit: (courseId, text) =>
      request('/api/student/flow/submit', { body: { courseId: courseId, text: text } }),
    listenMark: (courseId, text, atSec) =>
      request('/api/student/listen/mark', { body: { courseId: courseId, text: text, atSec: atSec } }),
    listenFinish: (courseId, seconds) =>
      request('/api/student/listen/finish', { body: { courseId: courseId, seconds: seconds } }),

    // ---------------- 教师端
    teacherState: () => request('/api/teacher/state'),
    teacherMaterials: () => request('/api/teacher/materials'),
    teacherStudents: () => request('/api/teacher/students'),
    teacherCourses: () => request('/api/teacher/courses'),
    teacherPublish: (title, genre, prompt, due) =>
      request('/api/teacher/publish', { body: { title: title, genre: genre, prompt: prompt, due: due } }),
    teacherClose: (courseId) =>
      request('/api/teacher/course/close', { body: { courseId: courseId } }),
    teacherPreview: (q) => request('/api/teacher/preview', { query: { q: q } }),
    teacherUpload: (filename, content) =>
      request('/api/teacher/upload', { body: { filename: filename, content: content } }),
    teacherResolve: (question) =>
      request('/api/teacher/resolve', { body: { question: question } }),

    health: () => request('/api/health')
  };

  global.API = api;
})(window);
