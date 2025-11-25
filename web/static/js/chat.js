// web/static/js/chat.js
(function () {
  const messagesEl = document.getElementById("messages");
  const formEl = document.getElementById("chat-form");
  const inputEl = document.getElementById("msg-input");
  const userListEl = document.getElementById("user-list");

  // 与后端建立 Socket.IO 连接，HTTPS 下自动用 wss
  const socket = io({
    transports: ["websocket"]
  });

  function appendMessage(text, user, time, isSystem) {
    const div = document.createElement("div");
    div.className = "msg" + (isSystem ? " system" : "");
    if (time) {
      const tSpan = document.createElement("span");
      tSpan.className = "time";
      tSpan.textContent = "[" + time + "]";
      div.appendChild(tSpan);
    }
    if (user && !isSystem) {
      const uSpan = document.createElement("span");
      uSpan.className = "user";
      uSpan.textContent = user + "：";
      div.appendChild(uSpan);
    }
    const textSpan = document.createElement("span");
    textSpan.className = "text";
    textSpan.textContent = text;
    div.appendChild(textSpan);

    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // 收到系统消息
  socket.on("system_message", function (data) {
    appendMessage(data.text, null, null, true);
  });

  // 收到聊天消息
  socket.on("chat_message", function (msg) {
    appendMessage(msg.text, msg.user, msg.time, false);
  });

  // 更新在线用户列表
  socket.on("online_users", function (users) {
    userListEl.innerHTML = "";
    users.forEach(function (name) {
      const li = document.createElement("li");
      li.textContent = name;
      if (window.me && name === window.me) {
        li.classList.add("me");
      }
      userListEl.appendChild(li);
    });
  });

  // 发送消息
  formEl.addEventListener("submit", function (e) {
    e.preventDefault();
    const text = inputEl.value.trim();
    if (!text) return;
    socket.emit("chat_message", { text: text });
    inputEl.value = "";
  });

})();
