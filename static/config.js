// Since frontend and backend are served from the same domain (monolith),
// we use an empty string so all fetch calls are relative (e.g. /api/analyze).
// If you ever split them again, replace "" with your backend URL.
const CONFIG = {
    BACKEND_URL: ""
};
