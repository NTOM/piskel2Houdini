(function () {
  var ns = $.namespace('pskl.controller.settings.preferences');

  ns.PcgPreferencesController = function (piskelController, preferencesController) {
    this.piskelController = piskelController;
    this.preferencesController = preferencesController;
  };

  pskl.utils.inherit(ns.PcgPreferencesController, pskl.controller.settings.AbstractSettingController);

  ns.PcgPreferencesController.prototype.init = function () {
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

    // 5) 发送到本地调度服务（默认 5050 端口）
    try {
      var payload = JSON.parse(requestJsonString);
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

  ns.PcgPreferencesController.prototype.destroy = function () {
    this.superclass.destroy.call(this);
  };
})();


