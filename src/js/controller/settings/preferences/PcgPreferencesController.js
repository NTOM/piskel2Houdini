(function () {
  var ns = $.namespace('pskl.controller.settings.preferences');

  ns.PcgPreferencesController = function (piskelController, preferencesController) {
    this.piskelController = piskelController;
    this.preferencesController = preferencesController;
  };

  pskl.utils.inherit(ns.PcgPreferencesController, pskl.controller.settings.AbstractSettingController);

  ns.PcgPreferencesController.prototype.init = function () {
    // 初始化 users 输入框（默认6位[a-zA-Z]随机）
    var usersInput = document.querySelector('.pcg-users-input');
    var currentUsers = pskl.UserSettings.get(pskl.UserSettings.PCG_USERS);
    if (!currentUsers) {
      currentUsers = this.generateRandomUsers_();
      pskl.UserSettings.set(pskl.UserSettings.PCG_USERS, currentUsers);
    }
    // 初始化 user_time（会话级）：存入 sessionStorage，关闭页面后自动失效
    var userTimeCompact = null;
    try {
      userTimeCompact = window.sessionStorage.getItem('PCG_USER_TIME_COMPACT');
    } catch (e) {}
    if (!userTimeCompact) {
      userTimeCompact = this.generateCompactBeijingTime_();
      try { window.sessionStorage.setItem('PCG_USER_TIME_COMPACT', userTimeCompact); } catch (e) {}
    }
    if (usersInput) {
      usersInput.value = currentUsers;
      this.addEventListener(usersInput, 'change', function (evt) {
        var val = (evt.target.value || '').trim();
        if (!val) {
          val = this.generateRandomUsers_();
        }
        pskl.UserSettings.set(pskl.UserSettings.PCG_USERS, val);
      }.bind(this));
      // Random 按钮
      var randomBtn = document.querySelector('.pcg-users-random-btn');
      if (randomBtn) {
        this.addEventListener(randomBtn, 'click', function () {
          var newVal = this.generateRandomUsers_();
          usersInput.value = newVal;
          pskl.UserSettings.set(pskl.UserSettings.PCG_USERS, newVal);
        }.bind(this));
      }
    }

    // 初始化 area_layout_seed 输入框
    var input = document.querySelector('.pcg-area-seed-input');
    var current = pskl.UserSettings.get(pskl.UserSettings.AREA_LAYOUT_SEED);
    if (typeof current === 'undefined' || current === null) {
      current = 9624;
    }
    input.value = current;

    // 记录最近一次有效值，便于在失焦时回退
    this.lastValidSeed_ = current;

    // 输入过程中允许为空，不强制回退；仅在可解析为整数时更新设置
    this.addEventListener(input, 'input', this.onSeedInput_.bind(this));
    // 失焦/回车时，如为空则回退为最近一次有效值
    this.addEventListener(input, 'change', this.onSeedChange_.bind(this));

    // 绑定 Step1_RoomGen 按钮
    var step1Btn = document.querySelector('.pcg-step1-btn');
    if (step1Btn) {
      this.addEventListener(step1Btn, 'click', this.onClickStep1_.bind(this));
    }

    // 绑定 Step3 按钮（暂时为空实现）
    var step3Btn = document.querySelector('.pcg-step3-btn');
    if (step3Btn) {
      this.addEventListener(step3Btn, 'click', this.onClickStep3_.bind(this));
    }

    // 绑定 Step4 帮助按钮（列出Theme信息）
    var step4HelpBtn = document.querySelector('.pcg-step4-help-btn');
    if (step4HelpBtn) {
      this.addEventListener(step4HelpBtn, 'click', this.onClickStep4Help_.bind(this));
    }
  };

  ns.PcgPreferencesController.prototype.onSeedInput_ = function (evt) {
    var str = (evt.target.value || '').trim();
    if (str === '') {
      // 允许清空，暂不写入设置
      return;
    }
    var value = parseInt(str, 10);
    if (!isNaN(value)) {
      pskl.UserSettings.set(pskl.UserSettings.AREA_LAYOUT_SEED, value);
      this.lastValidSeed_ = value;
    }
    // 非法输入时不回退，允许用户继续编辑
  };

  ns.PcgPreferencesController.prototype.onSeedChange_ = function (evt) {
    var str = (evt.target.value || '').trim();
    if (str === '') {
      // 失焦时为空：恢复到最近一次有效值
      evt.target.value = this.lastValidSeed_;
      return;
    }
    var value = parseInt(str, 10);
    if (!isNaN(value)) {
      pskl.UserSettings.set(pskl.UserSettings.AREA_LAYOUT_SEED, value);
      this.lastValidSeed_ = value;
    } else {
      // 非法则恢复
      evt.target.value = this.lastValidSeed_;
    }
  };

  ns.PcgPreferencesController.prototype.onClickStep1_ = function () {
    // 1) 读取模板
    var template = pskl.utils.Template.get('pcg-step1-request-template');
    if (!template) { return; }

    // 2) 生成UUID
    var uuid = this.generateUUID_();

    // 3) 收集参数：从用户设置读取 area_layout_seed
    var seed = pskl.UserSettings.get(pskl.UserSettings.AREA_LAYOUT_SEED) || 9624;

    // 4) 替换模板中的占位符
    var requestJsonString = pskl.utils.Template.replace(template, {
      'area_layout_seed': seed,
      'uuid': uuid
    });

    // 5) 组装 user_id 与 request_time（北京时间 ISO8601）
    var users = pskl.UserSettings.get(pskl.UserSettings.PCG_USERS) || this.generateRandomUsers_();
    var requestTime = this.generateBeijingIsoTime_();
    var userTimeCompact = null;
    try { userTimeCompact = window.sessionStorage.getItem('PCG_USER_TIME_COMPACT'); } catch (e) {}
    // 确保 userTimeCompact 存在（极端情况下会话中缺失时重新生成）
    if (!userTimeCompact) {
      userTimeCompact = this.generateCompactBeijingTime_();
      try { window.sessionStorage.setItem('PCG_USER_TIME_COMPACT', userTimeCompact); } catch (e) {}
    }
    var userId = users + '_' + userTimeCompact;

    // 6) 发送到本地调度服务（默认 5050 端口）
    try {
      var payload = JSON.parse(requestJsonString);
      payload.user_id = userId;
      payload.request_time = requestTime;
      var url = 'http://127.0.0.1:5050/cook';
      var hipPath = payload.hip;
      var self = this;

      // 显示 Processing 遮罩
      this.showProcessing_('Processing...');

      pskl.utils.Xhr.xhr_(url, 'POST', function (xhr) {
        // 成功回调：打印结果
        var text = xhr.responseText || '{}';
        console.log('[PCG] Step1_RoomGen success:', text);
        // 解析响应，尝试拉取PNG
        try {
          var resp = JSON.parse(text);
          var respUuid = (resp && resp.post && resp.post.json && resp.post.json.uuid) ||
            payload.uuid || uuid;
          if (resp && resp.post && resp.post.ok && respUuid && hipPath) {
            var pngUrl = 'http://127.0.0.1:5050/result/png?hip=' +
              encodeURIComponent(hipPath) +
              '&uuid=' + encodeURIComponent(respUuid);
            self.fetchAndImportPng_(pngUrl, function () {
              self.hideProcessing_();
            });
          } else {
            // 没有有效的 post 结果，直接隐藏遮罩
            self.hideProcessing_();
          }
        } catch (e) {
          console.warn('[PCG] parse response failed:', e);
          self.hideProcessing_();
        }
      }, function (err, xhr) {
        console.error('[PCG] Step1_RoomGen error:', err, xhr && xhr.responseText);
        self.hideProcessing_();
      }).send(JSON.stringify(payload));
    } catch (e) {
      console.error('[PCG] Step1_RoomGen invalid template JSON:', e);
      this.hideProcessing_();
    }
  };

  /**
   * 拉取PNG并导入到当前画布（复用Piskel内置导入流程）。
   * @param {string} pngUrl
   * @param {Function=} doneCb 结束回调（无论成功失败均调用）
   */
  ns.PcgPreferencesController.prototype.fetchAndImportPng_ = function (pngUrl, doneCb) {
    try {
      var xhr = new XMLHttpRequest();
      xhr.open('GET', pngUrl, true);
      xhr.responseType = 'blob';
      xhr.onload = function () {
        if (xhr.status === 200) {
          var blob = xhr.response;
          try {
            var file = new File([blob], 'pcg-result.png', {type: 'image/png'});
            $.publish(Events.DIALOG_SHOW, {
              dialogId: 'import',
              initArgs: { rawFiles: [file] }
            });
            console.log('[PCG] PNG fetched and passed to Import dialog');
          } catch (e) {
            console.error('[PCG] wrap blob to File failed:', e);
          }
        } else {
          console.error('[PCG] fetch png failed:', xhr.status, xhr.responseText);
        }
        if (doneCb) { doneCb(); }
      };
      xhr.onerror = function (e) {
        console.error('[PCG] fetch png xhr error:', e);
        if (doneCb) { doneCb(); }
      };
      xhr.send();
    } catch (e) {
      console.error('[PCG] fetchAndImportPng_ failed:', e);
      if (doneCb) { doneCb(); }
    }
  };

  /** 显示Processing遮罩 */
  ns.PcgPreferencesController.prototype.showProcessing_ = function (text) {
    if (this._pcgOverlay_) { return; }
    var overlay = document.createElement('div');
    overlay.className = 'pcg-processing-overlay';
    overlay.style.position = 'fixed';
    overlay.style.left = '0';
    overlay.style.top = '0';
    overlay.style.right = '0';
    overlay.style.bottom = '0';
    overlay.style.background = 'rgba(0,0,0,0.4)';
    overlay.style.zIndex = '10000';
    overlay.style.display = 'flex';
    overlay.style.alignItems = 'center';
    overlay.style.justifyContent = 'center';

    var box = document.createElement('div');
    box.style.background = '#222';
    box.style.color = '#fff';
    box.style.padding = '16px 24px';
    box.style.borderRadius = '6px';
    box.style.fontSize = '14px';
    box.textContent = text || 'Processing...';

    overlay.appendChild(box);
    document.body.appendChild(overlay);
    this._pcgOverlay_ = overlay;
  };

  /** 隐藏Processing遮罩 */
  ns.PcgPreferencesController.prototype.hideProcessing_ = function () {
    var overlay = this._pcgOverlay_;
    if (overlay && overlay.parentNode) {
      overlay.parentNode.removeChild(overlay);
    }
    this._pcgOverlay_ = null;
  };

  /**
   * Step3按钮点击处理（room_regen任务）
   */
  ns.PcgPreferencesController.prototype.onClickStep3_ = function () {
    var template = pskl.utils.Template.get('pcg-step3-request-template');
    if (!template) { return; }

    var uuid = this.generateUUID_();

    var requestJsonString = pskl.utils.Template.replace(template, {
      'uuid': uuid,
      'room_recalculate_file': uuid,
      'room_recalculate_input': uuid
    });

    try {
      var payload = JSON.parse(requestJsonString);
      var users = pskl.UserSettings.get(pskl.UserSettings.PCG_USERS) || this.generateRandomUsers_();
      var requestTime = this.generateBeijingIsoTime_();
      var userTimeCompact = null;
      try { userTimeCompact = window.sessionStorage.getItem('PCG_USER_TIME_COMPACT'); } catch (e) {}
      // 确保 userTimeCompact 存在（极端情况下会话中缺失时重新生成）
      if (!userTimeCompact) {
        userTimeCompact = this.generateCompactBeijingTime_();
        try { window.sessionStorage.setItem('PCG_USER_TIME_COMPACT', userTimeCompact); } catch (e) {}
      }
      payload.user_id = users + '_' + userTimeCompact;
      payload.request_time = requestTime;
      var url = 'http://127.0.0.1:5050/cook';
      var hipPath = payload.hip;
      var self = this;

      this.showProcessing_('Processing...');

      // 1) 先导出spritesheet为PNG Blob
      this.exportSpritesheetAsBlob_(function (blob) {
        if (!blob) {
          console.error('[PCG] Step3 export sprite failed: empty blob');
          self.hideProcessing_();
          return;
        }
        var filename = uuid + '.png';
        // 2) 先上传PNG到后端
        self.uploadPngToServer_(blob, filename, hipPath, uuid, function (ok) {
          if (!ok) {
            console.error('[PCG] Step3 upload png failed');
            self.hideProcessing_();
            return;
          }
          // 3) 上传成功后，再发送/cook请求，不再拉取结果PNG
          pskl.utils.Xhr.xhr_(url, 'POST', function (xhr) {
            var text = xhr.responseText || '{}';
            console.log('[PCG] Step3_RoomRegen success:', text);
            self.hideProcessing_();
          }, function (err, xhr) {
            console.error('[PCG] Step3_RoomRegen error:', err, xhr && xhr.responseText);
            self.hideProcessing_();
          }).send(JSON.stringify(payload));
        });
      });
    } catch (e) {
      console.error('[PCG] Step3_RoomRegen invalid template JSON:', e);
      this.hideProcessing_();
    }
  };

  /**
   * Step4：仅请求后端读取主题配置并以文本返回，前端弹框展示。
   */
  ns.PcgPreferencesController.prototype.onClickStep4Help_ = function () {
    var template = pskl.utils.Template.get('pcg-step4-request-template');
    if (!template) { return; }

    var uuid = this.generateUUID_();
    var requestJsonString = pskl.utils.Template.replace(template, {
      'uuid': uuid
    });

    try {
      var payload = JSON.parse(requestJsonString);
      // 不参与统一日志系统：不添加 user_id/request_time
      var url = 'http://127.0.0.1:5050/cook';

      var self = this;
      this.showProcessing_('Loading themes...');
      pskl.utils.Xhr.xhr_(url, 'POST', function (xhr) {
        var text = xhr.responseText || '{}';
        var msg = '';
        try {
          var resp = JSON.parse(text);
          if (resp && resp.ok && resp.themes && resp.themes.length) {
            self.hideProcessing_();
            self.showThemesDialog_(resp.themes);
            return;
          }
          if (resp && resp.ok && resp.lines && resp.lines.length) {
            msg = resp.lines.join('\n');
          } else if (resp && resp.ok && resp.text) {
            msg = String(resp.text);
          } else {
            msg = text;
          }
        } catch (e) {
          msg = text;
        }
        self.hideProcessing_();
        self.showAlertDialog_('可用主题', msg);
      }, function (err, xhr) {
        self.hideProcessing_();
        var msg = (xhr && xhr.responseText) ? xhr.responseText : String(err || 'request error');
        self.showAlertDialog_('获取主题失败', msg);
      }).send(JSON.stringify(payload));
    } catch (e) {
      this.hideProcessing_();
      this.showAlertDialog_('请求构建失败', String(e));
    }
  };

  /** 简易提示框（复用DOM，避免引入额外库） */
  ns.PcgPreferencesController.prototype.showAlertDialog_ = function (title, message) {
    try {
      var wrap = document.createElement('div');
      wrap.style.position = 'fixed';
      wrap.style.left = '0';
      wrap.style.top = '0';
      wrap.style.right = '0';
      wrap.style.bottom = '0';
      wrap.style.background = 'rgba(0,0,0,0.45)';
      wrap.style.zIndex = '10001';
      wrap.style.display = 'flex';
      wrap.style.alignItems = 'center';
      wrap.style.justifyContent = 'center';

      var panel = document.createElement('div');
      panel.style.background = '#222';
      panel.style.color = '#fff';
      panel.style.minWidth = '360px';
      panel.style.maxWidth = '720px';
      panel.style.maxHeight = '70vh';
      panel.style.overflow = 'auto';
      panel.style.borderRadius = '8px';
      panel.style.boxShadow = '0 6px 24px rgba(0,0,0,0.35)';
      panel.style.padding = '16px 16px 12px 16px';

      var h = document.createElement('div');
      h.style.fontSize = '16px';
      h.style.fontWeight = 'bold';
      h.style.marginBottom = '10px';
      h.textContent = title || 'Info';

      var pre = document.createElement('pre');
      pre.style.whiteSpace = 'pre-wrap';
      pre.style.wordBreak = 'break-word';
      pre.style.margin = '0 0 12px 0';
      pre.textContent = message || '';

      var btn = document.createElement('button');
      btn.className = 'button';
      btn.textContent = 'OK';
      btn.style.minWidth = '80px';
      btn.onclick = function () {
        if (wrap && wrap.parentNode) { wrap.parentNode.removeChild(wrap); }
      };

      panel.appendChild(h);
      panel.appendChild(pre);
      panel.appendChild(btn);
      wrap.appendChild(panel);
      document.body.appendChild(wrap);
    } catch (e) {
      alert(message || '');
    }
  };

  /** 主题列表对话框：表格 + 一键应用主色 */
  ns.PcgPreferencesController.prototype.showThemesDialog_ = function (themes) {
    try {
      var wrap = document.createElement('div');
      wrap.style.position = 'fixed';
      wrap.style.left = '0';
      wrap.style.top = '0';
      wrap.style.right = '0';
      wrap.style.bottom = '0';
      wrap.style.background = 'rgba(0,0,0,0.45)';
      wrap.style.zIndex = '10001';
      wrap.style.display = 'flex';
      wrap.style.alignItems = 'center';
      wrap.style.justifyContent = 'center';

      var panel = document.createElement('div');
      panel.style.background = '#222';
      panel.style.color = '#fff';
      panel.style.minWidth = '520px';
      panel.style.maxWidth = '900px';
      panel.style.maxHeight = '70vh';
      panel.style.overflow = 'auto';
      panel.style.borderRadius = '8px';
      panel.style.boxShadow = '0 6px 24px rgba(0,0,0,0.35)';
      panel.style.padding = '16px 16px 12px 16px';

      var h = document.createElement('div');
      h.style.fontSize = '16px';
      h.style.fontWeight = 'bold';
      h.style.marginBottom = '10px';
      h.textContent = '可用主题';

      var table = document.createElement('table');
      table.style.width = '100%';
      table.style.borderCollapse = 'collapse';
      table.style.marginBottom = '12px';

      var thead = document.createElement('thead');
      var trh = document.createElement('tr');
      var th1 = document.createElement('th');
      th1.textContent = 'Theme';
      th1.style.textAlign = 'left';
      th1.style.borderBottom = '1px solid #444';
      th1.style.padding = '6px 4px';
      var th2 = document.createElement('th');
      th2.textContent = 'Color';
      th2.style.textAlign = 'left';
      th2.style.borderBottom = '1px solid #444';
      th2.style.padding = '6px 4px';
      var th3 = document.createElement('th');
      th3.textContent = 'Desc';
      th3.style.textAlign = 'left';
      th3.style.borderBottom = '1px solid #444';
      th3.style.padding = '6px 4px';
      var th4 = document.createElement('th');
      th4.textContent = '操作';
      th4.style.textAlign = 'left';
      th4.style.borderBottom = '1px solid #444';
      th4.style.padding = '6px 4px';
      trh.appendChild(th1);
      trh.appendChild(th2);
      trh.appendChild(th3);
      trh.appendChild(th4);
      thead.appendChild(trh);
      table.appendChild(thead);

      var tbody = document.createElement('tbody');

      var normalizeHex = function (c) {
        if (!c) { return ''; }
        c = String(c).trim();
        if (!c) { return ''; }
        if (c[0] !== '#') { c = '#' + c; }
        return c.toLowerCase();
      };

      themes.forEach(function (item) {
        var name = (item && (item.name || item.theme)) || '';
        var color = normalizeHex(item && (item.color || item.hex || item.colour));
        var desc = (item && (item.description || item.desc || item.note)) || '';

        var tr = document.createElement('tr');
        var td1 = document.createElement('td');
        td1.textContent = name;
        td1.style.padding = '6px 4px';
        td1.style.borderBottom = '1px solid #333';
        var td2 = document.createElement('td');
        td2.style.padding = '6px 4px';
        td2.style.borderBottom = '1px solid #333';
        var swatch = document.createElement('span');
        swatch.textContent = color || '-';
        swatch.style.display = 'inline-flex';
        swatch.style.alignItems = 'center';
        swatch.style.gap = '8px';
        var box = document.createElement('span');
        box.style.display = 'inline-block';
        box.style.width = '14px';
        box.style.height = '14px';
        box.style.border = '1px solid #555';
        box.style.background = color || 'transparent';
        swatch.prepend(box);
        td2.appendChild(swatch);

        var td3 = document.createElement('td');
        td3.textContent = desc;
        td3.style.padding = '6px 4px';
        td3.style.borderBottom = '1px solid #333';
        var td4 = document.createElement('td');
        td4.style.padding = '6px 4px';
        td4.style.borderBottom = '1px solid #333';
        var btn = document.createElement('button');
        btn.className = 'button';
        btn.textContent = '应用主色';
        btn.disabled = !color;
        btn.onclick = function () {
          try {
            if (!color) { return; }
            if (pskl && pskl.app && pskl.app.paletteController &&
                pskl.app.paletteController.setPrimaryColor_) {
              pskl.app.paletteController.setPrimaryColor_(color);
            } else {
              // 兜底：仅发布事件（可能不更新UI选择器）
              $.publish(Events.PRIMARY_COLOR_SELECTED, [color]);
            }
          } catch (e) {}
        };
        td4.appendChild(btn);

        tr.appendChild(td1);
        tr.appendChild(td2);
        tr.appendChild(td3);
        tr.appendChild(td4);
        tbody.appendChild(tr);
      });

      table.appendChild(tbody);

      var footer = document.createElement('div');
      footer.style.textAlign = 'right';
      var closeBtn = document.createElement('button');
      closeBtn.className = 'button';
      closeBtn.textContent = '关闭';
      closeBtn.onclick = function () {
        if (wrap && wrap.parentNode) { wrap.parentNode.removeChild(wrap); }
      };
      footer.appendChild(closeBtn);

      panel.appendChild(h);
      panel.appendChild(table);
      panel.appendChild(footer);
      wrap.appendChild(panel);
      document.body.appendChild(wrap);
    } catch (e) {
      // fallback 到文本提示
      var lines = [];
      try {
        for (var i = 0; i < themes.length; i++) {
          var t = themes[i] || {};
          var name = t.name || t.theme || '';
          var color = t.color || t.hex || t.colour || '';
          var desc = t.description || t.desc || t.note || '';
          lines.push('Theme: ' + name + '    Color: ' + color + '    Desc: ' + desc);
        }
      } catch (e2) {}
      this.showAlertDialog_('可用主题', lines.join('\n'));
    }
  };

  /**
   * 导出当前工程为spritesheet PNG的Blob（等价于导出面板中的download行为，默认zoom=1，最佳列数）
   * @param {Function} cb 接收一个Blob参数
   */
  ns.PcgPreferencesController.prototype.exportSpritesheetAsBlob_ = function (cb) {
    try {
      var piskelController = this.piskelController;
      var renderer = new pskl.rendering.PiskelRenderer(piskelController);
      var columns = this.computeBestFitColumns_();
      var rows = Math.ceil(piskelController.getFrameCount() / columns);
      var canvas = renderer.renderAsCanvas(columns, rows);
      // 目前固定zoom=1；如需一致与导出面板，可扩展读取exportController的zoom
      pskl.utils.BlobUtils.canvasToBlob(canvas, function (blob) {
        cb(blob);
      });
    } catch (e) {
      console.error('[PCG] exportSpritesheetAsBlob_ failed:', e);
      cb(null);
    }
  };

  /** 计算与导出面板一致的最佳列数 */
  ns.PcgPreferencesController.prototype.computeBestFitColumns_ = function () {
    try {
      var ratio = this.piskelController.getWidth() / this.piskelController.getHeight();
      var frameCount = this.piskelController.getFrameCount();
      var bestFit = Math.round(Math.sqrt(frameCount / ratio));
      // clamp到[1, frameCount]
      return pskl.utils.Math.minmax(bestFit, 1, frameCount);
    } catch (e) {
      return 1;
    }
  };

  /**
   * 上传PNG到后端
   * 约定后端存在POST /upload/png?hip=<...>&uuid=<...> 接收文件字段为file
   */
  ns.PcgPreferencesController.prototype.uploadPngToServer_ = function (blob, filename, hipPath, uuid, cb) {
    try {
      var form = new FormData();
      form.append('file', blob, filename);
      var uploadUrl = 'http://127.0.0.1:5050/upload/png?hip=' + encodeURIComponent(hipPath) +
        '&uuid=' + encodeURIComponent(uuid);
      var xhr = new XMLHttpRequest();
      xhr.open('POST', uploadUrl, true);
      xhr.onload = function () {
        var ok = (xhr.status >= 200 && xhr.status < 300);
        if (!ok) {
          console.error('[PCG] upload response:', xhr.status, xhr.responseText);
        }
        cb(!!ok);
      };
      xhr.onerror = function (e) {
        console.error('[PCG] upload xhr error:', e);
        cb(false);
      };
      xhr.send(form);
    } catch (e) {
      console.error('[PCG] uploadPngToServer_ failed:', e);
      cb(false);
    }
  };

  /**
   * 生成UUID v4
   * @private
   * @returns {string} UUID字符串
   */
  ns.PcgPreferencesController.prototype.generateUUID_ = function () {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      var r = Math.random() * 16 | 0;
      var v = c == 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  };

  /** 生成6位[a-zA-Z]随机字符串 */
  ns.PcgPreferencesController.prototype.generateRandomUsers_ = function () {
    var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
    var out = '';
    for (var i = 0; i < 6; i++) {
      out += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return out;
  };

  /** 生成北京时间 ISO8601（到秒） */
  ns.PcgPreferencesController.prototype.generateBeijingIsoTime_ = function () {
    var d = new Date();
    // 计算北京时间：基于本地时间偏移得到东八区时间
    var utc = d.getTime() + (d.getTimezoneOffset() * 60000);
    var bj = new Date(utc + 8 * 3600000);
    // 格式化到秒，并附加+08:00偏移
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    var iso = bj.getFullYear() + '-' + pad(bj.getMonth() + 1) + '-' + pad(bj.getDate()) +
      'T' + pad(bj.getHours()) + ':' + pad(bj.getMinutes()) + ':' + pad(bj.getSeconds()) + '+08:00';
    return iso;
  };

  /** 生成紧凑型北京时间 YYYYMMDDHHmm（到分钟，用于文件名安全） */
  ns.PcgPreferencesController.prototype.generateCompactBeijingTime_ = function () {
    var d = new Date();
    var utc = d.getTime() + (d.getTimezoneOffset() * 60000);
    var bj = new Date(utc + 8 * 3600000);
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    var y = bj.getFullYear();
    var m = pad(bj.getMonth() + 1);
    var d2 = pad(bj.getDate());
    var h = pad(bj.getHours());
    var mm = pad(bj.getMinutes());
    return '' + y + m + d2 + h + mm;
  };

  ns.PcgPreferencesController.prototype.destroy = function () {
    this.superclass.destroy.call(this);
  };
})();


