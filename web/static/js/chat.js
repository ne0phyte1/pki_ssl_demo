// web/static/js/chat.js
(function () {
  const messagesEl = document.getElementById("messages");
  const formEl = document.getElementById("chat-form");
  const inputEl = document.getElementById("msg-input");
  const userListEl = document.getElementById("user-list");
  const userRoomsListEl = document.getElementById("user-rooms-list");
  const allRoomsListEl = document.getElementById("all-rooms-list");
  const privateChatsListEl = document.getElementById("private-chats-list");
  const currentRoomEl = document.getElementById("current-room");
  const privateChatControls = document.querySelector(".private-chat-controls");
  const privateChatWithEl = document.getElementById("private-chat-with");
  const exitPrivateChatBtn = document.getElementById("exit-private-chat");

  // 与后端建立 Socket.IO 连接，HTTPS 下自动用 wss
  const socket = io({
    transports: ["websocket"]
  });

  // 当前状态
  let currentRoom = 'general';
  let currentPrivateChat = null;

  // 设置当前用户
  const meElement = document.querySelector('.me');
  if (meElement) {
    window.me = meElement.textContent.replace('我：', '').trim();
  } else {
    console.error('无法找到.me元素，请检查HTML结构');
    window.me = '未知用户';
  }

  function appendMessage(text, user, time, isSystem, isPrivate) {
    const div = document.createElement("div");
    const isOwnMessage = user === '我' || user === window.me;
    div.className = "msg" + (isSystem ? " system" : "") + (isPrivate ? " private" : "") + (isOwnMessage ? " own" : "");
    
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

    // 添加到私聊列表（如果是私人消息）
    if (isPrivate && !isSystem && user !== '我' && user !== window.me) {
      addToPrivateChatsList(user);
    }
  }

  // 添加用户到私聊列表
  function addToPrivateChatsList(username) {
    if (username === window.me) return;
    
    // 检查是否已经在列表中
    const existingItems = privateChatsListEl.querySelectorAll('li span');
    let exists = false;
    existingItems.forEach(item => {
      if (item.textContent === username) {
        exists = true;
      }
    });
    
    if (!exists) {
      const li = document.createElement("li");
      li.innerHTML = `
        <span>${username}</span>
      `;
      li.style.cursor = 'pointer';
      li.addEventListener('click', function() {
        currentPrivateChat = username;
        privateChatControls.style.display = 'block';
        privateChatWithEl.textContent = `私人聊天: ${username}`;
        inputEl.placeholder = `发送给 ${username}...`;
        // 加载私人消息历史
        socket.emit('load_private_history', { other_user: username });
      });
      
      // 添加到列表顶部
      privateChatsListEl.insertBefore(li, privateChatsListEl.firstChild);
    }
  }

  function clearMessages() {
    messagesEl.innerHTML = '';
  }

  function updateCurrentRoomDisplay(roomName) {
    currentRoom = roomName;
    currentRoomEl.textContent = `简化 QQ 安全通讯系统 - 当前聊天室: ${roomName}`;
  }


  // 私人聊天控制
  exitPrivateChatBtn.addEventListener('click', function() {
    currentPrivateChat = null;
    privateChatControls.style.display = 'none';
    inputEl.placeholder = "按 Enter 发送消息...";
    // 切换回当前聊天室
    socket.emit('switch_room', { room_name: currentRoom });
  });

  // 发送消息
  formEl.addEventListener("submit", function (e) {
    e.preventDefault();
    const text = inputEl.value.trim();
    if (!text) return;

    if (currentPrivateChat) {
      // 发送私人消息
      socket.emit('private_message', { to_user: currentPrivateChat, text: text });
    } else {
      // 发送聊天室消息
      socket.emit("chat_message", { text: text });
    }
    inputEl.value = "";
  });

  // Socket.IO 事件处理

  // 收到系统消息
  socket.on("system_message", function (data) {
    appendMessage(data.text, null, null, true);
  });

  // 收到聊天消息
  socket.on("chat_message", function (msg) {
    // 只有在当前聊天室的消息才显示
    if (msg.room === currentRoom && !currentPrivateChat) {
      appendMessage(msg.text, msg.user, msg.time, false);
    }
  });

  // 更新在线用户列表
  socket.on("online_users", function (users) {
    userListEl.innerHTML = "";
    users.forEach(function (name) {
      const li = document.createElement("li");
      li.textContent = name;
      if (name === window.me) {
        li.classList.add("me");
      } else {
        // 为其他用户添加点击事件以开始私人聊天
        li.style.cursor = 'pointer';
        li.addEventListener('click', function() {
          currentPrivateChat = name;
          privateChatControls.style.display = 'block';
          privateChatWithEl.textContent = `私人聊天: ${name}`;
          inputEl.placeholder = `发送给 ${name}...`;
          // 加载私人消息历史
          socket.emit('load_private_history', { other_user: name });
        });
      }
      userListEl.appendChild(li);
    });
  });

  // 收到聊天室列表
  socket.on("chat_rooms_list", function (rooms) {
    allRoomsListEl.innerHTML = "";
    rooms.forEach(function (room) {
      const li = document.createElement("li");
      li.innerHTML = `
        <span>${room.name}</span>
        <small>创建者: ${room.created_by}</small>
        <button class="join-room-btn" data-room="${room.name}">加入</button>
      `;
      allRoomsListEl.appendChild(li);
    });

    // 为加入按钮添加事件
    document.querySelectorAll('.join-room-btn').forEach(btn => {
      btn.addEventListener('click', function() {
        const roomName = this.getAttribute('data-room');
        socket.emit('join_room', { room_name: roomName });
      });
    });
  });

  // 收到用户加入的聊天室列表
  socket.on("user_rooms_list", function (rooms) {
    userRoomsListEl.innerHTML = "";
    rooms.forEach(function (roomName) {
      const li = document.createElement("li");
      li.innerHTML = `
        <span class="room-name ${roomName === currentRoom ? 'active' : ''}">${roomName}</span>
      `;
      
      // 左键点击进入聊天室
      li.addEventListener('click', function() {
        socket.emit('switch_room', { room_name: roomName });
      });
      
      userRoomsListEl.appendChild(li);
    });
  });


  // 收到聊天室历史
  socket.on("room_history", function (data) {
    clearMessages();
    updateCurrentRoomDisplay(data.room);
    data.history.forEach(function (msg) {
      appendMessage(msg.text, msg.user, msg.time, false);
    });
  });

  // 收到私人消息
  socket.on("private_message", function (msg) {
    // 如果正在与发送者或接收者进行私人聊天，则显示消息
    if (currentPrivateChat && (msg.from_user === currentPrivateChat || msg.to_user === currentPrivateChat)) {
      const displayName = msg.from_user === window.me ? '我' : msg.from_user;
      appendMessage(msg.text, displayName, msg.time, false, true);
    } else if (!currentPrivateChat) {
      // 如果不在私人聊天中，显示通知
      appendMessage(`收到来自 ${msg.from_user} 的私人消息: ${msg.text}`, null, null, true);
    }
  });

  // 收到私聊会话列表
  socket.on("private_chats_list", function (chats) {
    privateChatsListEl.innerHTML = "";
    chats.forEach(function (chat) {
      const li = document.createElement("li");
      li.innerHTML = `
        <span>${chat.partner}</span>
        <small>${new Date(chat.last_message_time).toLocaleTimeString()}</small>
      `;
      li.style.cursor = 'pointer';
      li.addEventListener('click', function() {
        currentPrivateChat = chat.partner;
        privateChatControls.style.display = 'block';
        privateChatWithEl.textContent = `私人聊天: ${chat.partner}`;
        inputEl.placeholder = `发送给 ${chat.partner}...`;
        // 加载私人消息历史
        socket.emit('load_private_history', { other_user: chat.partner });
      });
      
      privateChatsListEl.appendChild(li);
    });
  });

  // 收到私人消息历史
  socket.on("private_history", function (data) {
    clearMessages();
    data.history.forEach(function (msg) {
      const displayName = msg.from_user === window.me ? '我' : msg.from_user;
      appendMessage(msg.text, displayName, msg.time, false, true);
    });
  });


})();
