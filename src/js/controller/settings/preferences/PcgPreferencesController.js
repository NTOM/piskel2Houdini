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

    // 2) 收集参数：从用户设置读取 AREA_LAYOUT_SEED
    var seed = pskl.UserSettings.get(pskl.UserSettings.AREA_LAYOUT_SEED) || 9624;

    // 3) 替换模板中的占位符
    var requestJsonString = pskl.utils.Template.replace(template, {
      'AREA_LAYOUT_SEED': seed
    });

    // 4) 发送到本地调度服务（默认 5050 端口）
    try {
      var payload = JSON.parse(requestJsonString);
      var url = 'http://127.0.0.1:5050/cook';
      pskl.utils.Xhr.xhr_(url, 'POST', function (xhr) {
        // 成功回调：简单提示
        console.log('[PCG] Step1_RoomGen success:', xhr.responseText);
      }, function (err, xhr) {
        console.error('[PCG] Step1_RoomGen error:', err, xhr && xhr.responseText);
      }).send(JSON.stringify(payload));
    } catch (e) {
      console.error('[PCG] Step1_RoomGen invalid template JSON:', e);
    }
  };

  ns.PcgPreferencesController.prototype.destroy = function () {
    this.superclass.destroy.call(this);
  };
})();


