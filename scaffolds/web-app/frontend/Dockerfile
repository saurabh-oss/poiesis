FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Every top-level page, script and stylesheet: the shell, the UI kit, and (in an
# enterprise app) platform.js and platform.css.
COPY *.html *.js *.css /usr/share/nginx/html/
# Every story's screen. The old image copied only the three files above, so any
# extra module a story added would have been a 404 in the running app.
COPY screens /usr/share/nginx/html/screens
# Source Sans 3, Adobe's open face: bundled, so the app never depends on a font CDN.
COPY fonts /usr/share/nginx/html/fonts
EXPOSE 80
