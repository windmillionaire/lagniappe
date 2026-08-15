/*! Third-party licenses: /third-party-licenses.txt */
import { SearchBox } from './search.js?v=b2884058';
import { EntityMenu } from './entityMenu.js?v=b2884058';
import { w as withTransition, r as request, E as ENDPOINTS, g as generateElementId } from './foundation.js?v=b2884058';
import { c as connectivity } from './connectivity.js?v=b2884058';
import { Modal, OfflineModal, DeleteModal, HelpModal } from './modal.js?v=b2884058';
import { STYLES } from './styles.js?v=b2884058';
import { s as setIcon } from './icons.js?v=b2884058';
import { p as primitives } from './primitives.js?v=b2884058';
import { B as BaseForm, R as Renderer } from './baseForm.js?v=b2884058';
import { F as FacetsBox } from './facets.js?v=b2884058';

const CONDITION_REGISTRY = {
	html: () => import('./html.js?v=b2884058'),
	status: () => import('./status.js?v=b2884058'),
	visibility: () => import('./visibility.js?v=b2884058'),
	columns: () => import('./columns.js?v=b2884058'),
	options: () => import('./options.js?v=b2884058'),
};

/**
 * @testable infrastructure
 */
const loadCondition = async (builder, condition) => {
	const module = await CONDITION_REGISTRY[condition]();
	return new module.default(builder);
};

/**!
 * Sortable 1.15.7
 * @author	RubaXa   <trash@rubaxa.org>
 * @author	owenm    <owen23355@gmail.com>
 * @license MIT
 */
function _defineProperty(e, r, t) {
  return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, {
    value: t,
    enumerable: true,
    configurable: true,
    writable: true
  }) : e[r] = t, e;
}
function _extends() {
  return _extends = Object.assign ? Object.assign.bind() : function (n) {
    for (var e = 1; e < arguments.length; e++) {
      var t = arguments[e];
      for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]);
    }
    return n;
  }, _extends.apply(null, arguments);
}
function ownKeys(e, r) {
  var t = Object.keys(e);
  if (Object.getOwnPropertySymbols) {
    var o = Object.getOwnPropertySymbols(e);
    r && (o = o.filter(function (r) {
      return Object.getOwnPropertyDescriptor(e, r).enumerable;
    })), t.push.apply(t, o);
  }
  return t;
}
function _objectSpread2(e) {
  for (var r = 1; r < arguments.length; r++) {
    var t = null != arguments[r] ? arguments[r] : {};
    r % 2 ? ownKeys(Object(t), true).forEach(function (r) {
      _defineProperty(e, r, t[r]);
    }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) {
      Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r));
    });
  }
  return e;
}
function _objectWithoutProperties(e, t) {
  if (null == e) return {};
  var o,
    r,
    i = _objectWithoutPropertiesLoose(e, t);
  if (Object.getOwnPropertySymbols) {
    var n = Object.getOwnPropertySymbols(e);
    for (r = 0; r < n.length; r++) o = n[r], -1 === t.indexOf(o) && {}.propertyIsEnumerable.call(e, o) && (i[o] = e[o]);
  }
  return i;
}
function _objectWithoutPropertiesLoose(r, e) {
  if (null == r) return {};
  var t = {};
  for (var n in r) if ({}.hasOwnProperty.call(r, n)) {
    if (-1 !== e.indexOf(n)) continue;
    t[n] = r[n];
  }
  return t;
}
function _toPrimitive(t, r) {
  if ("object" != typeof t || !t) return t;
  var e = t[Symbol.toPrimitive];
  if (void 0 !== e) {
    var i = e.call(t, r);
    if ("object" != typeof i) return i;
    throw new TypeError("@@toPrimitive must return a primitive value.");
  }
  return ("string" === r ? String : Number)(t);
}
function _toPropertyKey(t) {
  var i = _toPrimitive(t, "string");
  return "symbol" == typeof i ? i : i + "";
}
function _typeof(o) {
  "@babel/helpers - typeof";

  return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) {
    return typeof o;
  } : function (o) {
    return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o;
  }, _typeof(o);
}

var version = "1.15.7";

function userAgent(pattern) {
  if (typeof window !== 'undefined' && window.navigator) {
    return !! /*@__PURE__*/navigator.userAgent.match(pattern);
  }
}
var IE11OrLess = userAgent(/(?:Trident.*rv[ :]?11\.|msie|iemobile|Windows Phone)/i);
var Edge = userAgent(/Edge/i);
var FireFox = userAgent(/firefox/i);
var Safari = userAgent(/safari/i) && !userAgent(/chrome/i) && !userAgent(/android/i);
var IOS = userAgent(/iP(ad|od|hone)/i);
var ChromeForAndroid = userAgent(/chrome/i) && userAgent(/android/i);

var captureMode = {
  capture: false,
  passive: false
};
function on(el, event, fn) {
  el.addEventListener(event, fn, !IE11OrLess && captureMode);
}
function off(el, event, fn) {
  el.removeEventListener(event, fn, !IE11OrLess && captureMode);
}
function matches( /**HTMLElement*/el, /**String*/selector) {
  if (!selector) return;
  selector[0] === '>' && (selector = selector.substring(1));
  if (el) {
    try {
      if (el.matches) {
        return el.matches(selector);
      } else if (el.msMatchesSelector) {
        return el.msMatchesSelector(selector);
      } else if (el.webkitMatchesSelector) {
        return el.webkitMatchesSelector(selector);
      }
    } catch (_) {
      return false;
    }
  }
  return false;
}
function getParentOrHost(el) {
  return el.host && el !== document && el.host.nodeType && el.host !== el ? el.host : el.parentNode;
}
function closest( /**HTMLElement*/el, /**String*/selector, /**HTMLElement*/ctx, includeCTX) {
  if (el) {
    ctx = ctx || document;
    do {
      if (selector != null && (selector[0] === '>' ? el.parentNode === ctx && matches(el, selector) : matches(el, selector)) || includeCTX && el === ctx) {
        return el;
      }
      if (el === ctx) break;
      /* jshint boss:true */
    } while (el = getParentOrHost(el));
  }
  return null;
}
var R_SPACE = /\s+/g;
function toggleClass(el, name, state) {
  if (el && name) {
    if (el.classList) {
      el.classList[state ? 'add' : 'remove'](name);
    } else {
      var className = (' ' + el.className + ' ').replace(R_SPACE, ' ').replace(' ' + name + ' ', ' ');
      el.className = (className + (state ? ' ' + name : '')).replace(R_SPACE, ' ');
    }
  }
}
function css(el, prop, val) {
  var style = el && el.style;
  if (style) {
    if (val === void 0) {
      if (document.defaultView && document.defaultView.getComputedStyle) {
        val = document.defaultView.getComputedStyle(el, '');
      } else if (el.currentStyle) {
        val = el.currentStyle;
      }
      return prop === void 0 ? val : val[prop];
    } else {
      if (!(prop in style) && prop.indexOf('webkit') === -1) {
        prop = '-webkit-' + prop;
      }
      style[prop] = val + (typeof val === 'string' ? '' : 'px');
    }
  }
}
function matrix(el, selfOnly) {
  var appliedTransforms = '';
  if (typeof el === 'string') {
    appliedTransforms = el;
  } else {
    do {
      var transform = css(el, 'transform');
      if (transform && transform !== 'none') {
        appliedTransforms = transform + ' ' + appliedTransforms;
      }
      /* jshint boss:true */
    } while (!selfOnly && (el = el.parentNode));
  }
  var matrixFn = window.DOMMatrix || window.WebKitCSSMatrix || window.CSSMatrix || window.MSCSSMatrix;
  /*jshint -W056 */
  return matrixFn && new matrixFn(appliedTransforms);
}
function find(ctx, tagName, iterator) {
  if (ctx) {
    var list = ctx.getElementsByTagName(tagName),
      i = 0,
      n = list.length;
    if (iterator) {
      for (; i < n; i++) {
        iterator(list[i], i);
      }
    }
    return list;
  }
  return [];
}
function getWindowScrollingElement() {
  var scrollingElement = document.scrollingElement;
  if (scrollingElement) {
    return scrollingElement;
  } else {
    return document.documentElement;
  }
}

/**
 * Returns the "bounding client rect" of given element
 * @param  {HTMLElement} el                       The element whose boundingClientRect is wanted
 * @param  {[Boolean]} relativeToContainingBlock  Whether the rect should be relative to the containing block of (including) the container
 * @param  {[Boolean]} relativeToNonStaticParent  Whether the rect should be relative to the relative parent of (including) the contaienr
 * @param  {[Boolean]} undoScale                  Whether the container's scale() should be undone
 * @param  {[HTMLElement]} container              The parent the element will be placed in
 * @return {Object}                               The boundingClientRect of el, with specified adjustments
 */
function getRect(el, relativeToContainingBlock, relativeToNonStaticParent, undoScale, container) {
  if (!el.getBoundingClientRect && el !== window) return;
  var elRect, top, left, bottom, right, height, width;
  if (el !== window && el.parentNode && el !== getWindowScrollingElement()) {
    elRect = el.getBoundingClientRect();
    top = elRect.top;
    left = elRect.left;
    bottom = elRect.bottom;
    right = elRect.right;
    height = elRect.height;
    width = elRect.width;
  } else {
    top = 0;
    left = 0;
    bottom = window.innerHeight;
    right = window.innerWidth;
    height = window.innerHeight;
    width = window.innerWidth;
  }
  if ((relativeToContainingBlock || relativeToNonStaticParent) && el !== window) {
    // Adjust for translate()
    container = container || el.parentNode;

    // solves #1123 (see: https://stackoverflow.com/a/37953806/6088312)
    // Not needed on <= IE11
    if (!IE11OrLess) {
      do {
        if (container && container.getBoundingClientRect && (css(container, 'transform') !== 'none' || relativeToNonStaticParent && css(container, 'position') !== 'static')) {
          var containerRect = container.getBoundingClientRect();

          // Set relative to edges of padding box of container
          top -= containerRect.top + parseInt(css(container, 'border-top-width'));
          left -= containerRect.left + parseInt(css(container, 'border-left-width'));
          bottom = top + elRect.height;
          right = left + elRect.width;
          break;
        }
        /* jshint boss:true */
      } while (container = container.parentNode);
    }
  }
  if (undoScale && el !== window) {
    // Adjust for scale()
    var elMatrix = matrix(container || el),
      scaleX = elMatrix && elMatrix.a,
      scaleY = elMatrix && elMatrix.d;
    if (elMatrix) {
      top /= scaleY;
      left /= scaleX;
      width /= scaleX;
      height /= scaleY;
      bottom = top + height;
      right = left + width;
    }
  }
  return {
    top: top,
    left: left,
    bottom: bottom,
    right: right,
    width: width,
    height: height
  };
}

/**
 * Checks if a side of an element is scrolled past a side of its parents
 * @param  {HTMLElement}  el           The element who's side being scrolled out of view is in question
 * @param  {String}       elSide       Side of the element in question ('top', 'left', 'right', 'bottom')
 * @param  {String}       parentSide   Side of the parent in question ('top', 'left', 'right', 'bottom')
 * @return {HTMLElement}               The parent scroll element that the el's side is scrolled past, or null if there is no such element
 */
function isScrolledPast(el, elSide, parentSide) {
  var parent = getParentAutoScrollElement(el, true),
    elSideVal = getRect(el)[elSide];

  /* jshint boss:true */
  while (parent) {
    var parentSideVal = getRect(parent)[parentSide],
      visible = void 0;
    {
      visible = elSideVal >= parentSideVal;
    }
    if (!visible) return parent;
    if (parent === getWindowScrollingElement()) break;
    parent = getParentAutoScrollElement(parent, false);
  }
  return false;
}

/**
 * Gets nth child of el, ignoring hidden children, sortable's elements (does not ignore clone if it's visible)
 * and non-draggable elements
 * @param  {HTMLElement} el       The parent element
 * @param  {Number} childNum      The index of the child
 * @param  {Object} options       Parent Sortable's options
 * @return {HTMLElement}          The child at index childNum, or null if not found
 */
function getChild(el, childNum, options, includeDragEl) {
  var currentChild = 0,
    i = 0,
    children = el.children;
  while (i < children.length) {
    if (children[i].style.display !== 'none' && children[i] !== Sortable.ghost && (includeDragEl || children[i] !== Sortable.dragged) && closest(children[i], options.draggable, el, false)) {
      if (currentChild === childNum) {
        return children[i];
      }
      currentChild++;
    }
    i++;
  }
  return null;
}

/**
 * Gets the last child in the el, ignoring ghostEl or invisible elements (clones)
 * @param  {HTMLElement} el       Parent element
 * @param  {selector} selector    Any other elements that should be ignored
 * @return {HTMLElement}          The last child, ignoring ghostEl
 */
function lastChild(el, selector) {
  var last = el.lastElementChild;
  while (last && (last === Sortable.ghost || css(last, 'display') === 'none' || selector && !matches(last, selector))) {
    last = last.previousElementSibling;
  }
  return last || null;
}

/**
 * Returns the index of an element within its parent for a selected set of
 * elements
 * @param  {HTMLElement} el
 * @param  {selector} selector
 * @return {number}
 */
function index(el, selector) {
  var index = 0;
  if (!el || !el.parentNode) {
    return -1;
  }

  /* jshint boss:true */
  while (el = el.previousElementSibling) {
    if (el.nodeName.toUpperCase() !== 'TEMPLATE' && el !== Sortable.clone && (!selector || matches(el, selector))) {
      index++;
    }
  }
  return index;
}

/**
 * Returns the scroll offset of the given element, added with all the scroll offsets of parent elements.
 * The value is returned in real pixels.
 * @param  {HTMLElement} el
 * @return {Array}             Offsets in the format of [left, top]
 */
function getRelativeScrollOffset(el) {
  var offsetLeft = 0,
    offsetTop = 0,
    winScroller = getWindowScrollingElement();
  if (el) {
    do {
      var elMatrix = matrix(el),
        scaleX = elMatrix.a,
        scaleY = elMatrix.d;
      offsetLeft += el.scrollLeft * scaleX;
      offsetTop += el.scrollTop * scaleY;
    } while (el !== winScroller && (el = el.parentNode));
  }
  return [offsetLeft, offsetTop];
}

/**
 * Returns the index of the object within the given array
 * @param  {Array} arr   Array that may or may not hold the object
 * @param  {Object} obj  An object that has a key-value pair unique to and identical to a key-value pair in the object you want to find
 * @return {Number}      The index of the object in the array, or -1
 */
function indexOfObject(arr, obj) {
  for (var i in arr) {
    if (!arr.hasOwnProperty(i)) continue;
    for (var key in obj) {
      if (obj.hasOwnProperty(key) && obj[key] === arr[i][key]) return Number(i);
    }
  }
  return -1;
}
function getParentAutoScrollElement(el, includeSelf) {
  // skip to window
  if (!el || !el.getBoundingClientRect) return getWindowScrollingElement();
  var elem = el;
  var gotSelf = false;
  do {
    // we don't need to get elem css if it isn't even overflowing in the first place (performance)
    if (elem.clientWidth < elem.scrollWidth || elem.clientHeight < elem.scrollHeight) {
      var elemCSS = css(elem);
      if (elem.clientWidth < elem.scrollWidth && (elemCSS.overflowX == 'auto' || elemCSS.overflowX == 'scroll') || elem.clientHeight < elem.scrollHeight && (elemCSS.overflowY == 'auto' || elemCSS.overflowY == 'scroll')) {
        if (!elem.getBoundingClientRect || elem === document.body) return getWindowScrollingElement();
        if (gotSelf || includeSelf) return elem;
        gotSelf = true;
      }
    }
    /* jshint boss:true */
  } while (elem = elem.parentNode);
  return getWindowScrollingElement();
}
function extend(dst, src) {
  if (dst && src) {
    for (var key in src) {
      if (src.hasOwnProperty(key)) {
        dst[key] = src[key];
      }
    }
  }
  return dst;
}
function isRectEqual(rect1, rect2) {
  return Math.round(rect1.top) === Math.round(rect2.top) && Math.round(rect1.left) === Math.round(rect2.left) && Math.round(rect1.height) === Math.round(rect2.height) && Math.round(rect1.width) === Math.round(rect2.width);
}
var _throttleTimeout;
function throttle(callback, ms) {
  return function () {
    if (!_throttleTimeout) {
      var args = arguments,
        _this = this;
      if (args.length === 1) {
        callback.call(_this, args[0]);
      } else {
        callback.apply(_this, args);
      }
      _throttleTimeout = setTimeout(function () {
        _throttleTimeout = void 0;
      }, ms);
    }
  };
}
function cancelThrottle() {
  clearTimeout(_throttleTimeout);
  _throttleTimeout = void 0;
}
function scrollBy(el, x, y) {
  el.scrollLeft += x;
  el.scrollTop += y;
}
function clone(el) {
  var Polymer = window.Polymer;
  var $ = window.jQuery || window.Zepto;
  if (Polymer && Polymer.dom) {
    return Polymer.dom(el).cloneNode(true);
  } else if ($) {
    return $(el).clone(true)[0];
  } else {
    return el.cloneNode(true);
  }
}
function getChildContainingRectFromElement(container, options, ghostEl) {
  var rect = {};
  Array.from(container.children).forEach(function (child) {
    var _rect$left, _rect$top, _rect$right, _rect$bottom;
    if (!closest(child, options.draggable, container, false) || child.animated || child === ghostEl) return;
    var childRect = getRect(child);
    rect.left = Math.min((_rect$left = rect.left) !== null && _rect$left !== void 0 ? _rect$left : Infinity, childRect.left);
    rect.top = Math.min((_rect$top = rect.top) !== null && _rect$top !== void 0 ? _rect$top : Infinity, childRect.top);
    rect.right = Math.max((_rect$right = rect.right) !== null && _rect$right !== void 0 ? _rect$right : -Infinity, childRect.right);
    rect.bottom = Math.max((_rect$bottom = rect.bottom) !== null && _rect$bottom !== void 0 ? _rect$bottom : -Infinity, childRect.bottom);
  });
  rect.width = rect.right - rect.left;
  rect.height = rect.bottom - rect.top;
  rect.x = rect.left;
  rect.y = rect.top;
  return rect;
}
var expando = 'Sortable' + new Date().getTime();

function AnimationStateManager() {
  var animationStates = [],
    animationCallbackId;
  return {
    captureAnimationState: function captureAnimationState() {
      animationStates = [];
      if (!this.options.animation) return;
      var children = [].slice.call(this.el.children);
      children.forEach(function (child) {
        if (css(child, 'display') === 'none' || child === Sortable.ghost) return;
        animationStates.push({
          target: child,
          rect: getRect(child)
        });
        var fromRect = _objectSpread2({}, animationStates[animationStates.length - 1].rect);

        // If animating: compensate for current animation
        if (child.thisAnimationDuration) {
          var childMatrix = matrix(child, true);
          if (childMatrix) {
            fromRect.top -= childMatrix.f;
            fromRect.left -= childMatrix.e;
          }
        }
        child.fromRect = fromRect;
      });
    },
    addAnimationState: function addAnimationState(state) {
      animationStates.push(state);
    },
    removeAnimationState: function removeAnimationState(target) {
      animationStates.splice(indexOfObject(animationStates, {
        target: target
      }), 1);
    },
    animateAll: function animateAll(callback) {
      var _this = this;
      if (!this.options.animation) {
        clearTimeout(animationCallbackId);
        if (typeof callback === 'function') callback();
        return;
      }
      var animating = false,
        animationTime = 0;
      animationStates.forEach(function (state) {
        var time = 0,
          target = state.target,
          fromRect = target.fromRect,
          toRect = getRect(target),
          prevFromRect = target.prevFromRect,
          prevToRect = target.prevToRect,
          animatingRect = state.rect,
          targetMatrix = matrix(target, true);
        if (targetMatrix) {
          // Compensate for current animation
          toRect.top -= targetMatrix.f;
          toRect.left -= targetMatrix.e;
        }
        target.toRect = toRect;
        if (target.thisAnimationDuration) {
          // Could also check if animatingRect is between fromRect and toRect
          if (isRectEqual(prevFromRect, toRect) && !isRectEqual(fromRect, toRect) &&
          // Make sure animatingRect is on line between toRect & fromRect
          (animatingRect.top - toRect.top) / (animatingRect.left - toRect.left) === (fromRect.top - toRect.top) / (fromRect.left - toRect.left)) {
            // If returning to same place as started from animation and on same axis
            time = calculateRealTime(animatingRect, prevFromRect, prevToRect, _this.options);
          }
        }

        // if fromRect != toRect: animate
        if (!isRectEqual(toRect, fromRect)) {
          target.prevFromRect = fromRect;
          target.prevToRect = toRect;
          if (!time) {
            time = _this.options.animation;
          }
          _this.animate(target, animatingRect, toRect, time);
        }
        if (time) {
          animating = true;
          animationTime = Math.max(animationTime, time);
          clearTimeout(target.animationResetTimer);
          target.animationResetTimer = setTimeout(function () {
            target.animationTime = 0;
            target.prevFromRect = null;
            target.fromRect = null;
            target.prevToRect = null;
            target.thisAnimationDuration = null;
          }, time);
          target.thisAnimationDuration = time;
        }
      });
      clearTimeout(animationCallbackId);
      if (!animating) {
        if (typeof callback === 'function') callback();
      } else {
        animationCallbackId = setTimeout(function () {
          if (typeof callback === 'function') callback();
        }, animationTime);
      }
      animationStates = [];
    },
    animate: function animate(target, currentRect, toRect, duration) {
      if (duration) {
        css(target, 'transition', '');
        css(target, 'transform', '');
        var elMatrix = matrix(this.el),
          scaleX = elMatrix && elMatrix.a,
          scaleY = elMatrix && elMatrix.d,
          translateX = (currentRect.left - toRect.left) / (scaleX || 1),
          translateY = (currentRect.top - toRect.top) / (scaleY || 1);
        target.animatingX = !!translateX;
        target.animatingY = !!translateY;
        css(target, 'transform', 'translate3d(' + translateX + 'px,' + translateY + 'px,0)');
        this.forRepaintDummy = repaint(target); // repaint

        css(target, 'transition', 'transform ' + duration + 'ms' + (this.options.easing ? ' ' + this.options.easing : ''));
        css(target, 'transform', 'translate3d(0,0,0)');
        typeof target.animated === 'number' && clearTimeout(target.animated);
        target.animated = setTimeout(function () {
          css(target, 'transition', '');
          css(target, 'transform', '');
          target.animated = false;
          target.animatingX = false;
          target.animatingY = false;
        }, duration);
      }
    }
  };
}
function repaint(target) {
  return target.offsetWidth;
}
function calculateRealTime(animatingRect, fromRect, toRect, options) {
  return Math.sqrt(Math.pow(fromRect.top - animatingRect.top, 2) + Math.pow(fromRect.left - animatingRect.left, 2)) / Math.sqrt(Math.pow(fromRect.top - toRect.top, 2) + Math.pow(fromRect.left - toRect.left, 2)) * options.animation;
}

var plugins = [];
var defaults = {
  initializeByDefault: true
};
var PluginManager = {
  mount: function mount(plugin) {
    // Set default static properties
    for (var option in defaults) {
      if (defaults.hasOwnProperty(option) && !(option in plugin)) {
        plugin[option] = defaults[option];
      }
    }
    plugins.forEach(function (p) {
      if (p.pluginName === plugin.pluginName) {
        throw "Sortable: Cannot mount plugin ".concat(plugin.pluginName, " more than once");
      }
    });
    plugins.push(plugin);
  },
  pluginEvent: function pluginEvent(eventName, sortable, evt) {
    var _this = this;
    this.eventCanceled = false;
    evt.cancel = function () {
      _this.eventCanceled = true;
    };
    var eventNameGlobal = eventName + 'Global';
    plugins.forEach(function (plugin) {
      if (!sortable[plugin.pluginName]) return;
      // Fire global events if it exists in this sortable
      if (sortable[plugin.pluginName][eventNameGlobal]) {
        sortable[plugin.pluginName][eventNameGlobal](_objectSpread2({
          sortable: sortable
        }, evt));
      }

      // Only fire plugin event if plugin is enabled in this sortable,
      // and plugin has event defined
      if (sortable.options[plugin.pluginName] && sortable[plugin.pluginName][eventName]) {
        sortable[plugin.pluginName][eventName](_objectSpread2({
          sortable: sortable
        }, evt));
      }
    });
  },
  initializePlugins: function initializePlugins(sortable, el, defaults, options) {
    plugins.forEach(function (plugin) {
      var pluginName = plugin.pluginName;
      if (!sortable.options[pluginName] && !plugin.initializeByDefault) return;
      var initialized = new plugin(sortable, el, sortable.options);
      initialized.sortable = sortable;
      initialized.options = sortable.options;
      sortable[pluginName] = initialized;

      // Add default options from plugin
      _extends(defaults, initialized.defaults);
    });
    for (var option in sortable.options) {
      if (!sortable.options.hasOwnProperty(option)) continue;
      var modified = this.modifyOption(sortable, option, sortable.options[option]);
      if (typeof modified !== 'undefined') {
        sortable.options[option] = modified;
      }
    }
  },
  getEventProperties: function getEventProperties(name, sortable) {
    var eventProperties = {};
    plugins.forEach(function (plugin) {
      if (typeof plugin.eventProperties !== 'function') return;
      _extends(eventProperties, plugin.eventProperties.call(sortable[plugin.pluginName], name));
    });
    return eventProperties;
  },
  modifyOption: function modifyOption(sortable, name, value) {
    var modifiedValue;
    plugins.forEach(function (plugin) {
      // Plugin must exist on the Sortable
      if (!sortable[plugin.pluginName]) return;

      // If static option listener exists for this option, call in the context of the Sortable's instance of this plugin
      if (plugin.optionListeners && typeof plugin.optionListeners[name] === 'function') {
        modifiedValue = plugin.optionListeners[name].call(sortable[plugin.pluginName], value);
      }
    });
    return modifiedValue;
  }
};

function dispatchEvent(_ref) {
  var sortable = _ref.sortable,
    rootEl = _ref.rootEl,
    name = _ref.name,
    targetEl = _ref.targetEl,
    cloneEl = _ref.cloneEl,
    toEl = _ref.toEl,
    fromEl = _ref.fromEl,
    oldIndex = _ref.oldIndex,
    newIndex = _ref.newIndex,
    oldDraggableIndex = _ref.oldDraggableIndex,
    newDraggableIndex = _ref.newDraggableIndex,
    originalEvent = _ref.originalEvent,
    putSortable = _ref.putSortable,
    extraEventProperties = _ref.extraEventProperties;
  sortable = sortable || rootEl && rootEl[expando];
  if (!sortable) return;
  var evt,
    options = sortable.options,
    onName = 'on' + name.charAt(0).toUpperCase() + name.substr(1);
  // Support for new CustomEvent feature
  if (window.CustomEvent && !IE11OrLess && !Edge) {
    evt = new CustomEvent(name, {
      bubbles: true,
      cancelable: true
    });
  } else {
    evt = document.createEvent('Event');
    evt.initEvent(name, true, true);
  }
  evt.to = toEl || rootEl;
  evt.from = fromEl || rootEl;
  evt.item = targetEl || rootEl;
  evt.clone = cloneEl;
  evt.oldIndex = oldIndex;
  evt.newIndex = newIndex;
  evt.oldDraggableIndex = oldDraggableIndex;
  evt.newDraggableIndex = newDraggableIndex;
  evt.originalEvent = originalEvent;
  evt.pullMode = putSortable ? putSortable.lastPutMode : undefined;
  var allEventProperties = _objectSpread2(_objectSpread2({}, extraEventProperties), PluginManager.getEventProperties(name, sortable));
  for (var option in allEventProperties) {
    evt[option] = allEventProperties[option];
  }
  if (rootEl) {
    rootEl.dispatchEvent(evt);
  }
  if (options[onName]) {
    options[onName].call(sortable, evt);
  }
}

var _excluded = ["evt"];
var pluginEvent = function pluginEvent(eventName, sortable) {
  var _ref = arguments.length > 2 && arguments[2] !== undefined ? arguments[2] : {},
    originalEvent = _ref.evt,
    data = _objectWithoutProperties(_ref, _excluded);
  PluginManager.pluginEvent.bind(Sortable)(eventName, sortable, _objectSpread2({
    dragEl: dragEl,
    parentEl: parentEl,
    ghostEl: ghostEl,
    rootEl: rootEl,
    nextEl: nextEl,
    lastDownEl: lastDownEl,
    cloneEl: cloneEl,
    cloneHidden: cloneHidden,
    dragStarted: moved,
    putSortable: putSortable,
    activeSortable: Sortable.active,
    originalEvent: originalEvent,
    oldIndex: oldIndex,
    oldDraggableIndex: oldDraggableIndex,
    newIndex: newIndex,
    newDraggableIndex: newDraggableIndex,
    hideGhostForTarget: _hideGhostForTarget,
    unhideGhostForTarget: _unhideGhostForTarget,
    cloneNowHidden: function cloneNowHidden() {
      cloneHidden = true;
    },
    cloneNowShown: function cloneNowShown() {
      cloneHidden = false;
    },
    dispatchSortableEvent: function dispatchSortableEvent(name) {
      _dispatchEvent({
        sortable: sortable,
        name: name,
        originalEvent: originalEvent
      });
    }
  }, data));
};
function _dispatchEvent(info) {
  dispatchEvent(_objectSpread2({
    putSortable: putSortable,
    cloneEl: cloneEl,
    targetEl: dragEl,
    rootEl: rootEl,
    oldIndex: oldIndex,
    oldDraggableIndex: oldDraggableIndex,
    newIndex: newIndex,
    newDraggableIndex: newDraggableIndex
  }, info));
}
var dragEl,
  parentEl,
  ghostEl,
  rootEl,
  nextEl,
  lastDownEl,
  cloneEl,
  cloneHidden,
  oldIndex,
  newIndex,
  oldDraggableIndex,
  newDraggableIndex,
  activeGroup,
  putSortable,
  awaitingDragStarted = false,
  ignoreNextClick = false,
  sortables = [],
  tapEvt,
  touchEvt,
  lastDx,
  lastDy,
  tapDistanceLeft,
  tapDistanceTop,
  moved,
  lastTarget,
  lastDirection,
  pastFirstInvertThresh = false,
  isCircumstantialInvert = false,
  targetMoveDistance,
  // For positioning ghost absolutely
  ghostRelativeParent,
  ghostRelativeParentInitialScroll = [],
  // (left, top)

  _silent = false,
  savedInputChecked = [];

/** @const */
var documentExists = typeof document !== 'undefined',
  PositionGhostAbsolutely = IOS,
  CSSFloatProperty = Edge || IE11OrLess ? 'cssFloat' : 'float',
  // This will not pass for IE9, because IE9 DnD only works on anchors
  supportDraggable = documentExists && !ChromeForAndroid && !IOS && 'draggable' in document.createElement('div'),
  supportCssPointerEvents = function () {
    if (!documentExists) return;
    // false when <= IE11
    if (IE11OrLess) {
      return false;
    }
    var el = document.createElement('x');
    el.style.cssText = 'pointer-events:auto';
    return el.style.pointerEvents === 'auto';
  }(),
  _detectDirection = function _detectDirection(el, options) {
    var elCSS = css(el),
      elWidth = parseInt(elCSS.width) - parseInt(elCSS.paddingLeft) - parseInt(elCSS.paddingRight) - parseInt(elCSS.borderLeftWidth) - parseInt(elCSS.borderRightWidth),
      child1 = getChild(el, 0, options),
      child2 = getChild(el, 1, options),
      firstChildCSS = child1 && css(child1),
      secondChildCSS = child2 && css(child2),
      firstChildWidth = firstChildCSS && parseInt(firstChildCSS.marginLeft) + parseInt(firstChildCSS.marginRight) + getRect(child1).width,
      secondChildWidth = secondChildCSS && parseInt(secondChildCSS.marginLeft) + parseInt(secondChildCSS.marginRight) + getRect(child2).width;
    if (elCSS.display === 'flex') {
      return elCSS.flexDirection === 'column' || elCSS.flexDirection === 'column-reverse' ? 'vertical' : 'horizontal';
    }
    if (elCSS.display === 'grid') {
      return elCSS.gridTemplateColumns.split(' ').length <= 1 ? 'vertical' : 'horizontal';
    }
    if (child1 && firstChildCSS["float"] && firstChildCSS["float"] !== 'none') {
      var touchingSideChild2 = firstChildCSS["float"] === 'left' ? 'left' : 'right';
      return child2 && (secondChildCSS.clear === 'both' || secondChildCSS.clear === touchingSideChild2) ? 'vertical' : 'horizontal';
    }
    return child1 && (firstChildCSS.display === 'block' || firstChildCSS.display === 'flex' || firstChildCSS.display === 'table' || firstChildCSS.display === 'grid' || firstChildWidth >= elWidth && elCSS[CSSFloatProperty] === 'none' || child2 && elCSS[CSSFloatProperty] === 'none' && firstChildWidth + secondChildWidth > elWidth) ? 'vertical' : 'horizontal';
  },
  _dragElInRowColumn = function _dragElInRowColumn(dragRect, targetRect, vertical) {
    var dragElS1Opp = vertical ? dragRect.left : dragRect.top,
      dragElS2Opp = vertical ? dragRect.right : dragRect.bottom,
      dragElOppLength = vertical ? dragRect.width : dragRect.height,
      targetS1Opp = vertical ? targetRect.left : targetRect.top,
      targetS2Opp = vertical ? targetRect.right : targetRect.bottom,
      targetOppLength = vertical ? targetRect.width : targetRect.height;
    return dragElS1Opp === targetS1Opp || dragElS2Opp === targetS2Opp || dragElS1Opp + dragElOppLength / 2 === targetS1Opp + targetOppLength / 2;
  },
  /**
   * Detects first nearest empty sortable to X and Y position using emptyInsertThreshold.
   * @param  {Number} x      X position
   * @param  {Number} y      Y position
   * @return {HTMLElement}   Element of the first found nearest Sortable
   */
  _detectNearestEmptySortable = function _detectNearestEmptySortable(x, y) {
    var ret;
    sortables.some(function (sortable) {
      var threshold = sortable[expando].options.emptyInsertThreshold;
      if (!threshold || lastChild(sortable)) return;
      var rect = getRect(sortable),
        insideHorizontally = x >= rect.left - threshold && x <= rect.right + threshold,
        insideVertically = y >= rect.top - threshold && y <= rect.bottom + threshold;
      if (insideHorizontally && insideVertically) {
        return ret = sortable;
      }
    });
    return ret;
  },
  _prepareGroup = function _prepareGroup(options) {
    function toFn(value, pull) {
      return function (to, from, dragEl, evt) {
        var sameGroup = to.options.group.name && from.options.group.name && to.options.group.name === from.options.group.name;
        if (value == null && (pull || sameGroup)) {
          // Default pull value
          // Default pull and put value if same group
          return true;
        } else if (value == null || value === false) {
          return false;
        } else if (pull && value === 'clone') {
          return value;
        } else if (typeof value === 'function') {
          return toFn(value(to, from, dragEl, evt), pull)(to, from, dragEl, evt);
        } else {
          var otherGroup = (pull ? to : from).options.group.name;
          return value === true || typeof value === 'string' && value === otherGroup || value.join && value.indexOf(otherGroup) > -1;
        }
      };
    }
    var group = {};
    var originalGroup = options.group;
    if (!originalGroup || _typeof(originalGroup) != 'object') {
      originalGroup = {
        name: originalGroup
      };
    }
    group.name = originalGroup.name;
    group.checkPull = toFn(originalGroup.pull, true);
    group.checkPut = toFn(originalGroup.put);
    group.revertClone = originalGroup.revertClone;
    options.group = group;
  },
  _hideGhostForTarget = function _hideGhostForTarget() {
    if (!supportCssPointerEvents && ghostEl) {
      css(ghostEl, 'display', 'none');
    }
  },
  _unhideGhostForTarget = function _unhideGhostForTarget() {
    if (!supportCssPointerEvents && ghostEl) {
      css(ghostEl, 'display', '');
    }
  };

// #1184 fix - Prevent click event on fallback if dragged but item not changed position
if (documentExists && !ChromeForAndroid) {
  document.addEventListener('click', function (evt) {
    if (ignoreNextClick) {
      evt.preventDefault();
      evt.stopPropagation && evt.stopPropagation();
      evt.stopImmediatePropagation && evt.stopImmediatePropagation();
      ignoreNextClick = false;
      return false;
    }
  }, true);
}
var nearestEmptyInsertDetectEvent = function nearestEmptyInsertDetectEvent(evt) {
  if (dragEl) {
    evt = evt.touches ? evt.touches[0] : evt;
    var nearest = _detectNearestEmptySortable(evt.clientX, evt.clientY);
    if (nearest) {
      // Create imitation event
      var event = {};
      for (var i in evt) {
        if (evt.hasOwnProperty(i)) {
          event[i] = evt[i];
        }
      }
      event.target = event.rootEl = nearest;
      event.preventDefault = void 0;
      event.stopPropagation = void 0;
      nearest[expando]._onDragOver(event);
    }
  }
};
var _checkOutsideTargetEl = function _checkOutsideTargetEl(evt) {
  if (dragEl) {
    dragEl.parentNode[expando]._isOutsideThisEl(evt.target);
  }
};

/**
 * @class  Sortable
 * @param  {HTMLElement}  el
 * @param  {Object}       [options]
 */
function Sortable(el, options) {
  if (!(el && el.nodeType && el.nodeType === 1)) {
    throw "Sortable: `el` must be an HTMLElement, not ".concat({}.toString.call(el));
  }
  this.el = el; // root element
  this.options = options = _extends({}, options);

  // Export instance
  el[expando] = this;
  var defaults = {
    group: null,
    sort: true,
    disabled: false,
    store: null,
    handle: null,
    draggable: /^[uo]l$/i.test(el.nodeName) ? '>li' : '>*',
    swapThreshold: 1,
    // percentage; 0 <= x <= 1
    invertSwap: false,
    // invert always
    invertedSwapThreshold: null,
    // will be set to same as swapThreshold if default
    removeCloneOnHide: true,
    direction: function direction() {
      return _detectDirection(el, this.options);
    },
    ghostClass: 'sortable-ghost',
    chosenClass: 'sortable-chosen',
    dragClass: 'sortable-drag',
    ignore: 'a, img',
    filter: null,
    preventOnFilter: true,
    animation: 0,
    easing: null,
    setData: function setData(dataTransfer, dragEl) {
      dataTransfer.setData('Text', dragEl.textContent);
    },
    dropBubble: false,
    dragoverBubble: false,
    dataIdAttr: 'data-id',
    delay: 0,
    delayOnTouchOnly: false,
    touchStartThreshold: (Number.parseInt ? Number : window).parseInt(window.devicePixelRatio, 10) || 1,
    forceFallback: false,
    fallbackClass: 'sortable-fallback',
    fallbackOnBody: false,
    fallbackTolerance: 0,
    fallbackOffset: {
      x: 0,
      y: 0
    },
    // Disabled on Safari: #1571; Enabled on Safari IOS: #2244
    supportPointer: Sortable.supportPointer !== false && 'PointerEvent' in window && (!Safari || IOS),
    emptyInsertThreshold: 5
  };
  PluginManager.initializePlugins(this, el, defaults);

  // Set default options
  for (var name in defaults) {
    !(name in options) && (options[name] = defaults[name]);
  }
  _prepareGroup(options);

  // Bind all private methods
  for (var fn in this) {
    if (fn.charAt(0) === '_' && typeof this[fn] === 'function') {
      this[fn] = this[fn].bind(this);
    }
  }

  // Setup drag mode
  this.nativeDraggable = options.forceFallback ? false : supportDraggable;
  if (this.nativeDraggable) {
    // Touch start threshold cannot be greater than the native dragstart threshold
    this.options.touchStartThreshold = 1;
  }

  // Bind events
  if (options.supportPointer) {
    on(el, 'pointerdown', this._onTapStart);
  } else {
    on(el, 'mousedown', this._onTapStart);
    on(el, 'touchstart', this._onTapStart);
  }
  if (this.nativeDraggable) {
    on(el, 'dragover', this);
    on(el, 'dragenter', this);
  }
  sortables.push(this.el);

  // Restore sorting
  options.store && options.store.get && this.sort(options.store.get(this) || []);

  // Add animation state manager
  _extends(this, AnimationStateManager());
}
Sortable.prototype = /** @lends Sortable.prototype */{
  constructor: Sortable,
  _isOutsideThisEl: function _isOutsideThisEl(target) {
    if (!this.el.contains(target) && target !== this.el) {
      lastTarget = null;
    }
  },
  _getDirection: function _getDirection(evt, target) {
    return typeof this.options.direction === 'function' ? this.options.direction.call(this, evt, target, dragEl) : this.options.direction;
  },
  _onTapStart: function _onTapStart( /** Event|TouchEvent */evt) {
    if (!evt.cancelable) return;
    var _this = this,
      el = this.el,
      options = this.options,
      preventOnFilter = options.preventOnFilter,
      type = evt.type,
      touch = evt.touches && evt.touches[0] || evt.pointerType && evt.pointerType === 'touch' && evt,
      target = (touch || evt).target,
      originalTarget = evt.target.shadowRoot && (evt.path && evt.path[0] || evt.composedPath && evt.composedPath()[0]) || target,
      filter = options.filter;
    _saveInputCheckedState(el);

    // Don't trigger start event when an element is been dragged, otherwise the evt.oldindex always wrong when set option.group.
    if (dragEl) {
      return;
    }
    if (/mousedown|pointerdown/.test(type) && evt.button !== 0 || options.disabled) {
      return; // only left button and enabled
    }

    // cancel dnd if original target is content editable
    if (originalTarget.isContentEditable) {
      return;
    }

    // Safari ignores further event handling after mousedown
    if (!this.nativeDraggable && Safari && target && target.tagName.toUpperCase() === 'SELECT') {
      return;
    }
    target = closest(target, options.draggable, el, false);
    if (target && target.animated) {
      return;
    }
    if (lastDownEl === target) {
      // Ignoring duplicate `down`
      return;
    }

    // Get the index of the dragged element within its parent
    oldIndex = index(target);
    oldDraggableIndex = index(target, options.draggable);

    // Check filter
    if (typeof filter === 'function') {
      if (filter.call(this, evt, target, this)) {
        _dispatchEvent({
          sortable: _this,
          rootEl: originalTarget,
          name: 'filter',
          targetEl: target,
          toEl: el,
          fromEl: el
        });
        pluginEvent('filter', _this, {
          evt: evt
        });
        preventOnFilter && evt.preventDefault();
        return; // cancel dnd
      }
    } else if (filter) {
      filter = filter.split(',').some(function (criteria) {
        criteria = closest(originalTarget, criteria.trim(), el, false);
        if (criteria) {
          _dispatchEvent({
            sortable: _this,
            rootEl: criteria,
            name: 'filter',
            targetEl: target,
            fromEl: el,
            toEl: el
          });
          pluginEvent('filter', _this, {
            evt: evt
          });
          return true;
        }
      });
      if (filter) {
        preventOnFilter && evt.preventDefault();
        return; // cancel dnd
      }
    }
    if (options.handle && !closest(originalTarget, options.handle, el, false)) {
      return;
    }

    // Prepare `dragstart`
    this._prepareDragStart(evt, touch, target);
  },
  _prepareDragStart: function _prepareDragStart( /** Event */evt, /** Touch */touch, /** HTMLElement */target) {
    var _this = this,
      el = _this.el,
      options = _this.options,
      ownerDocument = el.ownerDocument,
      dragStartFn;
    if (target && !dragEl && target.parentNode === el) {
      var dragRect = getRect(target);
      rootEl = el;
      dragEl = target;
      parentEl = dragEl.parentNode;
      nextEl = dragEl.nextSibling;
      lastDownEl = target;
      activeGroup = options.group;
      Sortable.dragged = dragEl;
      tapEvt = {
        target: dragEl,
        clientX: (touch || evt).clientX,
        clientY: (touch || evt).clientY
      };
      tapDistanceLeft = tapEvt.clientX - dragRect.left;
      tapDistanceTop = tapEvt.clientY - dragRect.top;
      this._lastX = (touch || evt).clientX;
      this._lastY = (touch || evt).clientY;
      dragEl.style['will-change'] = 'all';
      dragStartFn = function dragStartFn() {
        pluginEvent('delayEnded', _this, {
          evt: evt
        });
        if (Sortable.eventCanceled) {
          _this._onDrop();
          return;
        }
        // Delayed drag has been triggered
        // we can re-enable the events: touchmove/mousemove
        _this._disableDelayedDragEvents();
        if (!FireFox && _this.nativeDraggable) {
          dragEl.draggable = true;
        }

        // Bind the events: dragstart/dragend
        _this._triggerDragStart(evt, touch);

        // Drag start event
        _dispatchEvent({
          sortable: _this,
          name: 'choose',
          originalEvent: evt
        });

        // Chosen item
        toggleClass(dragEl, options.chosenClass, true);
      };

      // Disable "draggable"
      options.ignore.split(',').forEach(function (criteria) {
        find(dragEl, criteria.trim(), _disableDraggable);
      });
      on(ownerDocument, 'dragover', nearestEmptyInsertDetectEvent);
      on(ownerDocument, 'mousemove', nearestEmptyInsertDetectEvent);
      on(ownerDocument, 'touchmove', nearestEmptyInsertDetectEvent);
      if (options.supportPointer) {
        on(ownerDocument, 'pointerup', _this._onDrop);
        // Native D&D triggers pointercancel
        !this.nativeDraggable && on(ownerDocument, 'pointercancel', _this._onDrop);
      } else {
        on(ownerDocument, 'mouseup', _this._onDrop);
        on(ownerDocument, 'touchend', _this._onDrop);
        on(ownerDocument, 'touchcancel', _this._onDrop);
      }

      // Make dragEl draggable (must be before delay for FireFox)
      if (FireFox && this.nativeDraggable) {
        this.options.touchStartThreshold = 4;
        dragEl.draggable = true;
      }
      pluginEvent('delayStart', this, {
        evt: evt
      });

      // Delay is impossible for native DnD in Edge or IE
      if (options.delay && (!options.delayOnTouchOnly || touch) && (!this.nativeDraggable || !(Edge || IE11OrLess))) {
        if (Sortable.eventCanceled) {
          this._onDrop();
          return;
        }
        // If the user moves the pointer or let go the click or touch
        // before the delay has been reached:
        // disable the delayed drag
        if (options.supportPointer) {
          on(ownerDocument, 'pointerup', _this._disableDelayedDrag);
          on(ownerDocument, 'pointercancel', _this._disableDelayedDrag);
        } else {
          on(ownerDocument, 'mouseup', _this._disableDelayedDrag);
          on(ownerDocument, 'touchend', _this._disableDelayedDrag);
          on(ownerDocument, 'touchcancel', _this._disableDelayedDrag);
        }
        on(ownerDocument, 'mousemove', _this._delayedDragTouchMoveHandler);
        on(ownerDocument, 'touchmove', _this._delayedDragTouchMoveHandler);
        options.supportPointer && on(ownerDocument, 'pointermove', _this._delayedDragTouchMoveHandler);
        _this._dragStartTimer = setTimeout(dragStartFn, options.delay);
      } else {
        dragStartFn();
      }
    }
  },
  _delayedDragTouchMoveHandler: function _delayedDragTouchMoveHandler( /** TouchEvent|PointerEvent **/e) {
    var touch = e.touches ? e.touches[0] : e;
    if (Math.max(Math.abs(touch.clientX - this._lastX), Math.abs(touch.clientY - this._lastY)) >= Math.floor(this.options.touchStartThreshold / (this.nativeDraggable && window.devicePixelRatio || 1))) {
      this._disableDelayedDrag();
    }
  },
  _disableDelayedDrag: function _disableDelayedDrag() {
    dragEl && _disableDraggable(dragEl);
    clearTimeout(this._dragStartTimer);
    this._disableDelayedDragEvents();
  },
  _disableDelayedDragEvents: function _disableDelayedDragEvents() {
    var ownerDocument = this.el.ownerDocument;
    off(ownerDocument, 'mouseup', this._disableDelayedDrag);
    off(ownerDocument, 'touchend', this._disableDelayedDrag);
    off(ownerDocument, 'touchcancel', this._disableDelayedDrag);
    off(ownerDocument, 'pointerup', this._disableDelayedDrag);
    off(ownerDocument, 'pointercancel', this._disableDelayedDrag);
    off(ownerDocument, 'mousemove', this._delayedDragTouchMoveHandler);
    off(ownerDocument, 'touchmove', this._delayedDragTouchMoveHandler);
    off(ownerDocument, 'pointermove', this._delayedDragTouchMoveHandler);
  },
  _triggerDragStart: function _triggerDragStart( /** Event */evt, /** Touch */touch) {
    touch = touch || evt.pointerType == 'touch' && evt;
    if (!this.nativeDraggable || touch) {
      if (this.options.supportPointer) {
        on(document, 'pointermove', this._onTouchMove);
      } else if (touch) {
        on(document, 'touchmove', this._onTouchMove);
      } else {
        on(document, 'mousemove', this._onTouchMove);
      }
    } else {
      on(dragEl, 'dragend', this);
      on(rootEl, 'dragstart', this._onDragStart);
    }
    try {
      if (document.selection) {
        _nextTick(function () {
          document.selection.empty();
        });
      } else {
        window.getSelection().removeAllRanges();
      }
    } catch (err) {}
  },
  _dragStarted: function _dragStarted(fallback, evt) {
    awaitingDragStarted = false;
    if (rootEl && dragEl) {
      pluginEvent('dragStarted', this, {
        evt: evt
      });
      if (this.nativeDraggable) {
        on(document, 'dragover', _checkOutsideTargetEl);
      }
      var options = this.options;

      // Apply effect
      !fallback && toggleClass(dragEl, options.dragClass, false);
      toggleClass(dragEl, options.ghostClass, true);
      Sortable.active = this;
      fallback && this._appendGhost();

      // Drag start event
      _dispatchEvent({
        sortable: this,
        name: 'start',
        originalEvent: evt
      });
    } else {
      this._nulling();
    }
  },
  _emulateDragOver: function _emulateDragOver() {
    if (touchEvt) {
      this._lastX = touchEvt.clientX;
      this._lastY = touchEvt.clientY;
      _hideGhostForTarget();
      var target = document.elementFromPoint(touchEvt.clientX, touchEvt.clientY);
      var parent = target;
      while (target && target.shadowRoot) {
        target = target.shadowRoot.elementFromPoint(touchEvt.clientX, touchEvt.clientY);
        if (target === parent) break;
        parent = target;
      }
      dragEl.parentNode[expando]._isOutsideThisEl(target);
      if (parent) {
        do {
          if (parent[expando]) {
            var inserted = void 0;
            inserted = parent[expando]._onDragOver({
              clientX: touchEvt.clientX,
              clientY: touchEvt.clientY,
              target: target,
              rootEl: parent
            });
            if (inserted && !this.options.dragoverBubble) {
              break;
            }
          }
          target = parent; // store last element
        }
        /* jshint boss:true */ while (parent = getParentOrHost(parent));
      }
      _unhideGhostForTarget();
    }
  },
  _onTouchMove: function _onTouchMove( /**TouchEvent*/evt) {
    if (tapEvt) {
      var options = this.options,
        fallbackTolerance = options.fallbackTolerance,
        fallbackOffset = options.fallbackOffset,
        touch = evt.touches ? evt.touches[0] : evt,
        ghostMatrix = ghostEl && matrix(ghostEl, true),
        scaleX = ghostEl && ghostMatrix && ghostMatrix.a,
        scaleY = ghostEl && ghostMatrix && ghostMatrix.d,
        relativeScrollOffset = PositionGhostAbsolutely && ghostRelativeParent && getRelativeScrollOffset(ghostRelativeParent),
        dx = (touch.clientX - tapEvt.clientX + fallbackOffset.x) / (scaleX || 1) + (relativeScrollOffset ? relativeScrollOffset[0] - ghostRelativeParentInitialScroll[0] : 0) / (scaleX || 1),
        dy = (touch.clientY - tapEvt.clientY + fallbackOffset.y) / (scaleY || 1) + (relativeScrollOffset ? relativeScrollOffset[1] - ghostRelativeParentInitialScroll[1] : 0) / (scaleY || 1);

      // only set the status to dragging, when we are actually dragging
      if (!Sortable.active && !awaitingDragStarted) {
        if (fallbackTolerance && Math.max(Math.abs(touch.clientX - this._lastX), Math.abs(touch.clientY - this._lastY)) < fallbackTolerance) {
          return;
        }
        this._onDragStart(evt, true);
      }
      if (ghostEl) {
        if (ghostMatrix) {
          ghostMatrix.e += dx - (lastDx || 0);
          ghostMatrix.f += dy - (lastDy || 0);
        } else {
          ghostMatrix = {
            a: 1,
            b: 0,
            c: 0,
            d: 1,
            e: dx,
            f: dy
          };
        }
        var cssMatrix = "matrix(".concat(ghostMatrix.a, ",").concat(ghostMatrix.b, ",").concat(ghostMatrix.c, ",").concat(ghostMatrix.d, ",").concat(ghostMatrix.e, ",").concat(ghostMatrix.f, ")");
        css(ghostEl, 'webkitTransform', cssMatrix);
        css(ghostEl, 'mozTransform', cssMatrix);
        css(ghostEl, 'msTransform', cssMatrix);
        css(ghostEl, 'transform', cssMatrix);
        lastDx = dx;
        lastDy = dy;
        touchEvt = touch;
      }
      evt.cancelable && evt.preventDefault();
    }
  },
  _appendGhost: function _appendGhost() {
    // Bug if using scale(): https://stackoverflow.com/questions/2637058
    // Not being adjusted for
    if (!ghostEl) {
      var container = this.options.fallbackOnBody ? document.body : rootEl,
        rect = getRect(dragEl, true, PositionGhostAbsolutely, true, container),
        options = this.options;

      // Position absolutely
      if (PositionGhostAbsolutely) {
        // Get relatively positioned parent
        ghostRelativeParent = container;
        while (css(ghostRelativeParent, 'position') === 'static' && css(ghostRelativeParent, 'transform') === 'none' && ghostRelativeParent !== document) {
          ghostRelativeParent = ghostRelativeParent.parentNode;
        }
        if (ghostRelativeParent !== document.body && ghostRelativeParent !== document.documentElement) {
          if (ghostRelativeParent === document) ghostRelativeParent = getWindowScrollingElement();
          rect.top += ghostRelativeParent.scrollTop;
          rect.left += ghostRelativeParent.scrollLeft;
        } else {
          ghostRelativeParent = getWindowScrollingElement();
        }
        ghostRelativeParentInitialScroll = getRelativeScrollOffset(ghostRelativeParent);
      }
      ghostEl = dragEl.cloneNode(true);
      toggleClass(ghostEl, options.ghostClass, false);
      toggleClass(ghostEl, options.fallbackClass, true);
      toggleClass(ghostEl, options.dragClass, true);
      css(ghostEl, 'transition', '');
      css(ghostEl, 'transform', '');
      css(ghostEl, 'box-sizing', 'border-box');
      css(ghostEl, 'margin', 0);
      css(ghostEl, 'top', rect.top);
      css(ghostEl, 'left', rect.left);
      css(ghostEl, 'width', rect.width);
      css(ghostEl, 'height', rect.height);
      css(ghostEl, 'opacity', '0.8');
      css(ghostEl, 'position', PositionGhostAbsolutely ? 'absolute' : 'fixed');
      css(ghostEl, 'zIndex', '100000');
      css(ghostEl, 'pointerEvents', 'none');
      Sortable.ghost = ghostEl;
      container.appendChild(ghostEl);

      // Set transform-origin
      css(ghostEl, 'transform-origin', tapDistanceLeft / parseInt(ghostEl.style.width) * 100 + '% ' + tapDistanceTop / parseInt(ghostEl.style.height) * 100 + '%');
    }
  },
  _onDragStart: function _onDragStart( /**Event*/evt, /**boolean*/fallback) {
    var _this = this;
    var dataTransfer = evt.dataTransfer;
    var options = _this.options;
    pluginEvent('dragStart', this, {
      evt: evt
    });
    if (Sortable.eventCanceled) {
      this._onDrop();
      return;
    }
    pluginEvent('setupClone', this);
    if (!Sortable.eventCanceled) {
      cloneEl = clone(dragEl);
      cloneEl.removeAttribute("id");
      cloneEl.draggable = false;
      cloneEl.style['will-change'] = '';
      this._hideClone();
      toggleClass(cloneEl, this.options.chosenClass, false);
      Sortable.clone = cloneEl;
    }

    // #1143: IFrame support workaround
    _this.cloneId = _nextTick(function () {
      pluginEvent('clone', _this);
      if (Sortable.eventCanceled) return;
      if (!_this.options.removeCloneOnHide) {
        rootEl.insertBefore(cloneEl, dragEl);
      }
      _this._hideClone();
      _dispatchEvent({
        sortable: _this,
        name: 'clone'
      });
    });
    !fallback && toggleClass(dragEl, options.dragClass, true);

    // Set proper drop events
    if (fallback) {
      ignoreNextClick = true;
      _this._loopId = setInterval(_this._emulateDragOver, 50);
    } else {
      // Undo what was set in _prepareDragStart before drag started
      off(document, 'mouseup', _this._onDrop);
      off(document, 'touchend', _this._onDrop);
      off(document, 'touchcancel', _this._onDrop);
      if (dataTransfer) {
        dataTransfer.effectAllowed = 'move';
        options.setData && options.setData.call(_this, dataTransfer, dragEl);
      }
      on(document, 'drop', _this);

      // #1276 fix:
      css(dragEl, 'transform', 'translateZ(0)');
    }
    awaitingDragStarted = true;
    _this._dragStartId = _nextTick(_this._dragStarted.bind(_this, fallback, evt));
    on(document, 'selectstart', _this);
    moved = true;
    window.getSelection().removeAllRanges();
    if (Safari) {
      css(document.body, 'user-select', 'none');
    }
  },
  // Returns true - if no further action is needed (either inserted or another condition)
  _onDragOver: function _onDragOver( /**Event*/evt) {
    var el = this.el,
      target = evt.target,
      dragRect,
      targetRect,
      revert,
      options = this.options,
      group = options.group,
      activeSortable = Sortable.active,
      isOwner = activeGroup === group,
      canSort = options.sort,
      fromSortable = putSortable || activeSortable,
      vertical,
      _this = this,
      completedFired = false;
    if (_silent) return;
    function dragOverEvent(name, extra) {
      pluginEvent(name, _this, _objectSpread2({
        evt: evt,
        isOwner: isOwner,
        axis: vertical ? 'vertical' : 'horizontal',
        revert: revert,
        dragRect: dragRect,
        targetRect: targetRect,
        canSort: canSort,
        fromSortable: fromSortable,
        target: target,
        completed: completed,
        onMove: function onMove(target, after) {
          return _onMove(rootEl, el, dragEl, dragRect, target, getRect(target), evt, after);
        },
        changed: changed
      }, extra));
    }

    // Capture animation state
    function capture() {
      dragOverEvent('dragOverAnimationCapture');
      _this.captureAnimationState();
      if (_this !== fromSortable) {
        fromSortable.captureAnimationState();
      }
    }

    // Return invocation when dragEl is inserted (or completed)
    function completed(insertion) {
      dragOverEvent('dragOverCompleted', {
        insertion: insertion
      });
      if (insertion) {
        // Clones must be hidden before folding animation to capture dragRectAbsolute properly
        if (isOwner) {
          activeSortable._hideClone();
        } else {
          activeSortable._showClone(_this);
        }
        if (_this !== fromSortable) {
          // Set ghost class to new sortable's ghost class
          toggleClass(dragEl, putSortable ? putSortable.options.ghostClass : activeSortable.options.ghostClass, false);
          toggleClass(dragEl, options.ghostClass, true);
        }
        if (putSortable !== _this && _this !== Sortable.active) {
          putSortable = _this;
        } else if (_this === Sortable.active && putSortable) {
          putSortable = null;
        }

        // Animation
        if (fromSortable === _this) {
          _this._ignoreWhileAnimating = target;
        }
        _this.animateAll(function () {
          dragOverEvent('dragOverAnimationComplete');
          _this._ignoreWhileAnimating = null;
        });
        if (_this !== fromSortable) {
          fromSortable.animateAll();
          fromSortable._ignoreWhileAnimating = null;
        }
      }

      // Null lastTarget if it is not inside a previously swapped element
      if (target === dragEl && !dragEl.animated || target === el && !target.animated) {
        lastTarget = null;
      }

      // no bubbling and not fallback
      if (!options.dragoverBubble && !evt.rootEl && target !== document) {
        dragEl.parentNode[expando]._isOutsideThisEl(evt.target);

        // Do not detect for empty insert if already inserted
        !insertion && nearestEmptyInsertDetectEvent(evt);
      }
      !options.dragoverBubble && evt.stopPropagation && evt.stopPropagation();
      return completedFired = true;
    }

    // Call when dragEl has been inserted
    function changed() {
      newIndex = index(dragEl);
      newDraggableIndex = index(dragEl, options.draggable);
      _dispatchEvent({
        sortable: _this,
        name: 'change',
        toEl: el,
        newIndex: newIndex,
        newDraggableIndex: newDraggableIndex,
        originalEvent: evt
      });
    }
    if (evt.preventDefault !== void 0) {
      evt.cancelable && evt.preventDefault();
    }
    target = closest(target, options.draggable, el, true);
    dragOverEvent('dragOver');
    if (Sortable.eventCanceled) return completedFired;
    if (dragEl.contains(evt.target) || target.animated && target.animatingX && target.animatingY || _this._ignoreWhileAnimating === target) {
      return completed(false);
    }
    ignoreNextClick = false;
    if (activeSortable && !options.disabled && (isOwner ? canSort || (revert = parentEl !== rootEl) // Reverting item into the original list
    : putSortable === this || (this.lastPutMode = activeGroup.checkPull(this, activeSortable, dragEl, evt)) && group.checkPut(this, activeSortable, dragEl, evt))) {
      vertical = this._getDirection(evt, target) === 'vertical';
      dragRect = getRect(dragEl);
      dragOverEvent('dragOverValid');
      if (Sortable.eventCanceled) return completedFired;
      if (revert) {
        parentEl = rootEl; // actualization
        capture();
        this._hideClone();
        dragOverEvent('revert');
        if (!Sortable.eventCanceled) {
          if (nextEl) {
            rootEl.insertBefore(dragEl, nextEl);
          } else {
            rootEl.appendChild(dragEl);
          }
        }
        return completed(true);
      }
      var elLastChild = lastChild(el, options.draggable);
      if (!elLastChild || _ghostIsLast(evt, vertical, this) && !elLastChild.animated) {
        // Insert to end of list

        // If already at end of list: Do not insert
        if (elLastChild === dragEl) {
          return completed(false);
        }

        // if there is a last element, it is the target
        if (elLastChild && el === evt.target) {
          target = elLastChild;
        }
        if (target) {
          targetRect = getRect(target);
        }
        if (_onMove(rootEl, el, dragEl, dragRect, target, targetRect, evt, !!target) !== false) {
          capture();
          if (elLastChild && elLastChild.nextSibling) {
            // the last draggable element is not the last node
            el.insertBefore(dragEl, elLastChild.nextSibling);
          } else {
            el.appendChild(dragEl);
          }
          parentEl = el; // actualization

          changed();
          return completed(true);
        }
      } else if (elLastChild && _ghostIsFirst(evt, vertical, this)) {
        // Insert to start of list
        var firstChild = getChild(el, 0, options, true);
        if (firstChild === dragEl) {
          return completed(false);
        }
        target = firstChild;
        targetRect = getRect(target);
        if (_onMove(rootEl, el, dragEl, dragRect, target, targetRect, evt, false) !== false) {
          capture();
          el.insertBefore(dragEl, firstChild);
          parentEl = el; // actualization

          changed();
          return completed(true);
        }
      } else if (target.parentNode === el) {
        targetRect = getRect(target);
        var direction = 0,
          targetBeforeFirstSwap,
          differentLevel = dragEl.parentNode !== el,
          differentRowCol = !_dragElInRowColumn(dragEl.animated && dragEl.toRect || dragRect, target.animated && target.toRect || targetRect, vertical),
          side1 = vertical ? 'top' : 'left',
          scrolledPastTop = isScrolledPast(target, 'top', 'top') || isScrolledPast(dragEl, 'top', 'top'),
          scrollBefore = scrolledPastTop ? scrolledPastTop.scrollTop : void 0;
        if (lastTarget !== target) {
          targetBeforeFirstSwap = targetRect[side1];
          pastFirstInvertThresh = false;
          isCircumstantialInvert = !differentRowCol && options.invertSwap || differentLevel;
        }
        direction = _getSwapDirection(evt, target, targetRect, vertical, differentRowCol ? 1 : options.swapThreshold, options.invertedSwapThreshold == null ? options.swapThreshold : options.invertedSwapThreshold, isCircumstantialInvert, lastTarget === target);
        var sibling;
        if (direction !== 0) {
          // Check if target is beside dragEl in respective direction (ignoring hidden elements)
          var dragIndex = index(dragEl);
          do {
            dragIndex -= direction;
            sibling = parentEl.children[dragIndex];
          } while (sibling && (css(sibling, 'display') === 'none' || sibling === ghostEl));
        }
        // If dragEl is already beside target: Do not insert
        if (direction === 0 || sibling === target) {
          return completed(false);
        }
        lastTarget = target;
        lastDirection = direction;
        var nextSibling = target.nextElementSibling,
          after = false;
        after = direction === 1;
        var moveVector = _onMove(rootEl, el, dragEl, dragRect, target, targetRect, evt, after);
        if (moveVector !== false) {
          if (moveVector === 1 || moveVector === -1) {
            after = moveVector === 1;
          }
          _silent = true;
          setTimeout(_unsilent, 30);
          capture();
          if (after && !nextSibling) {
            el.appendChild(dragEl);
          } else {
            target.parentNode.insertBefore(dragEl, after ? nextSibling : target);
          }

          // Undo chrome's scroll adjustment (has no effect on other browsers)
          if (scrolledPastTop) {
            scrollBy(scrolledPastTop, 0, scrollBefore - scrolledPastTop.scrollTop);
          }
          parentEl = dragEl.parentNode; // actualization

          // must be done before animation
          if (targetBeforeFirstSwap !== undefined && !isCircumstantialInvert) {
            targetMoveDistance = Math.abs(targetBeforeFirstSwap - getRect(target)[side1]);
          }
          changed();
          return completed(true);
        }
      }
      if (el.contains(dragEl)) {
        return completed(false);
      }
    }
    return false;
  },
  _ignoreWhileAnimating: null,
  _offMoveEvents: function _offMoveEvents() {
    off(document, 'mousemove', this._onTouchMove);
    off(document, 'touchmove', this._onTouchMove);
    off(document, 'pointermove', this._onTouchMove);
    off(document, 'dragover', nearestEmptyInsertDetectEvent);
    off(document, 'mousemove', nearestEmptyInsertDetectEvent);
    off(document, 'touchmove', nearestEmptyInsertDetectEvent);
  },
  _offUpEvents: function _offUpEvents() {
    var ownerDocument = this.el.ownerDocument;
    off(ownerDocument, 'mouseup', this._onDrop);
    off(ownerDocument, 'touchend', this._onDrop);
    off(ownerDocument, 'pointerup', this._onDrop);
    off(ownerDocument, 'pointercancel', this._onDrop);
    off(ownerDocument, 'touchcancel', this._onDrop);
    off(document, 'selectstart', this);
  },
  _onDrop: function _onDrop( /**Event*/evt) {
    var el = this.el,
      options = this.options;

    // Get the index of the dragged element within its parent
    newIndex = index(dragEl);
    newDraggableIndex = index(dragEl, options.draggable);
    pluginEvent('drop', this, {
      evt: evt
    });
    parentEl = dragEl && dragEl.parentNode;

    // Get again after plugin event
    newIndex = index(dragEl);
    newDraggableIndex = index(dragEl, options.draggable);
    if (Sortable.eventCanceled) {
      this._nulling();
      return;
    }
    awaitingDragStarted = false;
    isCircumstantialInvert = false;
    pastFirstInvertThresh = false;
    clearInterval(this._loopId);
    clearTimeout(this._dragStartTimer);
    _cancelNextTick(this.cloneId);
    _cancelNextTick(this._dragStartId);

    // Unbind events
    if (this.nativeDraggable) {
      off(document, 'drop', this);
      off(el, 'dragstart', this._onDragStart);
    }
    this._offMoveEvents();
    this._offUpEvents();
    if (Safari) {
      css(document.body, 'user-select', '');
    }
    css(dragEl, 'transform', '');
    if (evt) {
      if (moved) {
        evt.cancelable && evt.preventDefault();
        !options.dropBubble && evt.stopPropagation();
      }
      ghostEl && ghostEl.parentNode && ghostEl.parentNode.removeChild(ghostEl);
      if (rootEl === parentEl || putSortable && putSortable.lastPutMode !== 'clone') {
        // Remove clone(s)
        cloneEl && cloneEl.parentNode && cloneEl.parentNode.removeChild(cloneEl);
      }
      if (dragEl) {
        if (this.nativeDraggable) {
          off(dragEl, 'dragend', this);
        }
        _disableDraggable(dragEl);
        dragEl.style['will-change'] = '';

        // Remove classes
        // ghostClass is added in dragStarted
        if (moved && !awaitingDragStarted) {
          toggleClass(dragEl, putSortable ? putSortable.options.ghostClass : this.options.ghostClass, false);
        }
        toggleClass(dragEl, this.options.chosenClass, false);

        // Drag stop event
        _dispatchEvent({
          sortable: this,
          name: 'unchoose',
          toEl: parentEl,
          newIndex: null,
          newDraggableIndex: null,
          originalEvent: evt
        });
        if (rootEl !== parentEl) {
          if (newIndex >= 0) {
            // Add event
            _dispatchEvent({
              rootEl: parentEl,
              name: 'add',
              toEl: parentEl,
              fromEl: rootEl,
              originalEvent: evt
            });

            // Remove event
            _dispatchEvent({
              sortable: this,
              name: 'remove',
              toEl: parentEl,
              originalEvent: evt
            });

            // drag from one list and drop into another
            _dispatchEvent({
              rootEl: parentEl,
              name: 'sort',
              toEl: parentEl,
              fromEl: rootEl,
              originalEvent: evt
            });
            _dispatchEvent({
              sortable: this,
              name: 'sort',
              toEl: parentEl,
              originalEvent: evt
            });
          }
          putSortable && putSortable.save();
        } else {
          if (newIndex !== oldIndex) {
            if (newIndex >= 0) {
              // drag & drop within the same list
              _dispatchEvent({
                sortable: this,
                name: 'update',
                toEl: parentEl,
                originalEvent: evt
              });
              _dispatchEvent({
                sortable: this,
                name: 'sort',
                toEl: parentEl,
                originalEvent: evt
              });
            }
          }
        }
        if (Sortable.active) {
          /* jshint eqnull:true */
          if (newIndex == null || newIndex === -1) {
            newIndex = oldIndex;
            newDraggableIndex = oldDraggableIndex;
          }
          _dispatchEvent({
            sortable: this,
            name: 'end',
            toEl: parentEl,
            originalEvent: evt
          });

          // Save sorting
          this.save();
        }
      }
    }
    this._nulling();
  },
  _nulling: function _nulling() {
    pluginEvent('nulling', this);
    rootEl = dragEl = parentEl = ghostEl = nextEl = cloneEl = lastDownEl = cloneHidden = tapEvt = touchEvt = moved = newIndex = newDraggableIndex = oldIndex = oldDraggableIndex = lastTarget = lastDirection = putSortable = activeGroup = Sortable.dragged = Sortable.ghost = Sortable.clone = Sortable.active = null;
    var el = this.el;
    savedInputChecked.forEach(function (checkEl) {
      if (el.contains(checkEl)) {
        checkEl.checked = true;
      }
    });
    savedInputChecked.length = lastDx = lastDy = 0;
  },
  handleEvent: function handleEvent( /**Event*/evt) {
    switch (evt.type) {
      case 'drop':
      case 'dragend':
        this._onDrop(evt);
        break;
      case 'dragenter':
      case 'dragover':
        if (dragEl) {
          this._onDragOver(evt);
          _globalDragOver(evt);
        }
        break;
      case 'selectstart':
        evt.preventDefault();
        break;
    }
  },
  /**
   * Serializes the item into an array of string.
   * @returns {String[]}
   */
  toArray: function toArray() {
    var order = [],
      el,
      children = this.el.children,
      i = 0,
      n = children.length,
      options = this.options;
    for (; i < n; i++) {
      el = children[i];
      if (closest(el, options.draggable, this.el, false)) {
        order.push(el.getAttribute(options.dataIdAttr) || _generateId(el));
      }
    }
    return order;
  },
  /**
   * Sorts the elements according to the array.
   * @param  {String[]}  order  order of the items
   */
  sort: function sort(order, useAnimation) {
    var items = {},
      rootEl = this.el;
    this.toArray().forEach(function (id, i) {
      var el = rootEl.children[i];
      if (closest(el, this.options.draggable, rootEl, false)) {
        items[id] = el;
      }
    }, this);
    useAnimation && this.captureAnimationState();
    order.forEach(function (id) {
      if (items[id]) {
        rootEl.removeChild(items[id]);
        rootEl.appendChild(items[id]);
      }
    });
    useAnimation && this.animateAll();
  },
  /**
   * Save the current sorting
   */
  save: function save() {
    var store = this.options.store;
    store && store.set && store.set(this);
  },
  /**
   * For each element in the set, get the first element that matches the selector by testing the element itself and traversing up through its ancestors in the DOM tree.
   * @param   {HTMLElement}  el
   * @param   {String}       [selector]  default: `options.draggable`
   * @returns {HTMLElement|null}
   */
  closest: function closest$1(el, selector) {
    return closest(el, selector || this.options.draggable, this.el, false);
  },
  /**
   * Set/get option
   * @param   {string} name
   * @param   {*}      [value]
   * @returns {*}
   */
  option: function option(name, value) {
    var options = this.options;
    if (value === void 0) {
      return options[name];
    } else {
      var modifiedValue = PluginManager.modifyOption(this, name, value);
      if (typeof modifiedValue !== 'undefined') {
        options[name] = modifiedValue;
      } else {
        options[name] = value;
      }
      if (name === 'group') {
        _prepareGroup(options);
      }
    }
  },
  /**
   * Destroy
   */
  destroy: function destroy() {
    pluginEvent('destroy', this);
    var el = this.el;
    el[expando] = null;
    off(el, 'mousedown', this._onTapStart);
    off(el, 'touchstart', this._onTapStart);
    off(el, 'pointerdown', this._onTapStart);
    if (this.nativeDraggable) {
      off(el, 'dragover', this);
      off(el, 'dragenter', this);
    }
    // Remove draggable attributes
    Array.prototype.forEach.call(el.querySelectorAll('[draggable]'), function (el) {
      el.removeAttribute('draggable');
    });
    this._onDrop();
    this._disableDelayedDragEvents();
    sortables.splice(sortables.indexOf(this.el), 1);
    this.el = el = null;
  },
  _hideClone: function _hideClone() {
    if (!cloneHidden) {
      pluginEvent('hideClone', this);
      if (Sortable.eventCanceled) return;
      css(cloneEl, 'display', 'none');
      if (this.options.removeCloneOnHide && cloneEl.parentNode) {
        cloneEl.parentNode.removeChild(cloneEl);
      }
      cloneHidden = true;
    }
  },
  _showClone: function _showClone(putSortable) {
    if (putSortable.lastPutMode !== 'clone') {
      this._hideClone();
      return;
    }
    if (cloneHidden) {
      pluginEvent('showClone', this);
      if (Sortable.eventCanceled) return;

      // show clone at dragEl or original position
      if (dragEl.parentNode == rootEl && !this.options.group.revertClone) {
        rootEl.insertBefore(cloneEl, dragEl);
      } else if (nextEl) {
        rootEl.insertBefore(cloneEl, nextEl);
      } else {
        rootEl.appendChild(cloneEl);
      }
      if (this.options.group.revertClone) {
        this.animate(dragEl, cloneEl);
      }
      css(cloneEl, 'display', '');
      cloneHidden = false;
    }
  }
};
function _globalDragOver( /**Event*/evt) {
  if (evt.dataTransfer) {
    evt.dataTransfer.dropEffect = 'move';
  }
  evt.cancelable && evt.preventDefault();
}
function _onMove(fromEl, toEl, dragEl, dragRect, targetEl, targetRect, originalEvent, willInsertAfter) {
  var evt,
    sortable = fromEl[expando],
    onMoveFn = sortable.options.onMove,
    retVal;
  // Support for new CustomEvent feature
  if (window.CustomEvent && !IE11OrLess && !Edge) {
    evt = new CustomEvent('move', {
      bubbles: true,
      cancelable: true
    });
  } else {
    evt = document.createEvent('Event');
    evt.initEvent('move', true, true);
  }
  evt.to = toEl;
  evt.from = fromEl;
  evt.dragged = dragEl;
  evt.draggedRect = dragRect;
  evt.related = targetEl || toEl;
  evt.relatedRect = targetRect || getRect(toEl);
  evt.willInsertAfter = willInsertAfter;
  evt.originalEvent = originalEvent;
  fromEl.dispatchEvent(evt);
  if (onMoveFn) {
    retVal = onMoveFn.call(sortable, evt, originalEvent);
  }
  return retVal;
}
function _disableDraggable(el) {
  el.draggable = false;
}
function _unsilent() {
  _silent = false;
}
function _ghostIsFirst(evt, vertical, sortable) {
  var firstElRect = getRect(getChild(sortable.el, 0, sortable.options, true));
  var childContainingRect = getChildContainingRectFromElement(sortable.el, sortable.options, ghostEl);
  var spacer = 10;
  return vertical ? evt.clientX < childContainingRect.left - spacer || evt.clientY < firstElRect.top && evt.clientX < firstElRect.right : evt.clientY < childContainingRect.top - spacer || evt.clientY < firstElRect.bottom && evt.clientX < firstElRect.left;
}
function _ghostIsLast(evt, vertical, sortable) {
  var lastElRect = getRect(lastChild(sortable.el, sortable.options.draggable));
  var childContainingRect = getChildContainingRectFromElement(sortable.el, sortable.options, ghostEl);
  var spacer = 10;
  return vertical ? evt.clientX > childContainingRect.right + spacer || evt.clientY > lastElRect.bottom && evt.clientX > lastElRect.left : evt.clientY > childContainingRect.bottom + spacer || evt.clientX > lastElRect.right && evt.clientY > lastElRect.top;
}
function _getSwapDirection(evt, target, targetRect, vertical, swapThreshold, invertedSwapThreshold, invertSwap, isLastTarget) {
  var mouseOnAxis = vertical ? evt.clientY : evt.clientX,
    targetLength = vertical ? targetRect.height : targetRect.width,
    targetS1 = vertical ? targetRect.top : targetRect.left,
    targetS2 = vertical ? targetRect.bottom : targetRect.right,
    invert = false;
  if (!invertSwap) {
    // Never invert or create dragEl shadow when target movemenet causes mouse to move past the end of regular swapThreshold
    if (isLastTarget && targetMoveDistance < targetLength * swapThreshold) {
      // multiplied only by swapThreshold because mouse will already be inside target by (1 - threshold) * targetLength / 2
      // check if past first invert threshold on side opposite of lastDirection
      if (!pastFirstInvertThresh && (lastDirection === 1 ? mouseOnAxis > targetS1 + targetLength * invertedSwapThreshold / 2 : mouseOnAxis < targetS2 - targetLength * invertedSwapThreshold / 2)) {
        // past first invert threshold, do not restrict inverted threshold to dragEl shadow
        pastFirstInvertThresh = true;
      }
      if (!pastFirstInvertThresh) {
        // dragEl shadow (target move distance shadow)
        if (lastDirection === 1 ? mouseOnAxis < targetS1 + targetMoveDistance // over dragEl shadow
        : mouseOnAxis > targetS2 - targetMoveDistance) {
          return -lastDirection;
        }
      } else {
        invert = true;
      }
    } else {
      // Regular
      if (mouseOnAxis > targetS1 + targetLength * (1 - swapThreshold) / 2 && mouseOnAxis < targetS2 - targetLength * (1 - swapThreshold) / 2) {
        return _getInsertDirection(target);
      }
    }
  }
  invert = invert || invertSwap;
  if (invert) {
    // Invert of regular
    if (mouseOnAxis < targetS1 + targetLength * invertedSwapThreshold / 2 || mouseOnAxis > targetS2 - targetLength * invertedSwapThreshold / 2) {
      return mouseOnAxis > targetS1 + targetLength / 2 ? 1 : -1;
    }
  }
  return 0;
}

/**
 * Gets the direction dragEl must be swapped relative to target in order to make it
 * seem that dragEl has been "inserted" into that element's position
 * @param  {HTMLElement} target       The target whose position dragEl is being inserted at
 * @return {Number}                   Direction dragEl must be swapped
 */
function _getInsertDirection(target) {
  if (index(dragEl) < index(target)) {
    return 1;
  } else {
    return -1;
  }
}

/**
 * Generate id
 * @param   {HTMLElement} el
 * @returns {String}
 * @private
 */
function _generateId(el) {
  var str = el.tagName + el.className + el.src + el.href + el.textContent,
    i = str.length,
    sum = 0;
  while (i--) {
    sum += str.charCodeAt(i);
  }
  return sum.toString(36);
}
function _saveInputCheckedState(root) {
  savedInputChecked.length = 0;
  var inputs = root.getElementsByTagName('input');
  var idx = inputs.length;
  while (idx--) {
    var el = inputs[idx];
    el.checked && savedInputChecked.push(el);
  }
}
function _nextTick(fn) {
  return setTimeout(fn, 0);
}
function _cancelNextTick(id) {
  return clearTimeout(id);
}

// Fixed #973:
if (documentExists) {
  on(document, 'touchmove', function (evt) {
    if ((Sortable.active || awaitingDragStarted) && evt.cancelable) {
      evt.preventDefault();
    }
  });
}

// Export utils
Sortable.utils = {
  on: on,
  off: off,
  css: css,
  find: find,
  is: function is(el, selector) {
    return !!closest(el, selector, el, false);
  },
  extend: extend,
  throttle: throttle,
  closest: closest,
  toggleClass: toggleClass,
  clone: clone,
  index: index,
  nextTick: _nextTick,
  cancelNextTick: _cancelNextTick,
  detectDirection: _detectDirection,
  getChild: getChild,
  expando: expando
};

/**
 * Get the Sortable instance of an element
 * @param  {HTMLElement} element The element
 * @return {Sortable|undefined}         The instance of Sortable
 */
Sortable.get = function (element) {
  return element[expando];
};

/**
 * Mount a plugin to Sortable
 * @param  {...SortablePlugin|SortablePlugin[]} plugins       Plugins being mounted
 */
Sortable.mount = function () {
  for (var _len = arguments.length, plugins = new Array(_len), _key = 0; _key < _len; _key++) {
    plugins[_key] = arguments[_key];
  }
  if (plugins[0].constructor === Array) plugins = plugins[0];
  plugins.forEach(function (plugin) {
    if (!plugin.prototype || !plugin.prototype.constructor) {
      throw "Sortable: Mounted plugin must be a constructor function, not ".concat({}.toString.call(plugin));
    }
    if (plugin.utils) Sortable.utils = _objectSpread2(_objectSpread2({}, Sortable.utils), plugin.utils);
    PluginManager.mount(plugin);
  });
};

/**
 * Create sortable instance
 * @param {HTMLElement}  el
 * @param {Object}      [options]
 */
Sortable.create = function (el, options) {
  return new Sortable(el, options);
};

// Export
Sortable.version = version;

var autoScrolls = [],
  scrollEl,
  scrollRootEl,
  scrolling = false,
  lastAutoScrollX,
  lastAutoScrollY,
  touchEvt$1,
  pointerElemChangedInterval;
function AutoScrollPlugin() {
  function AutoScroll() {
    this.defaults = {
      scroll: true,
      forceAutoScrollFallback: false,
      scrollSensitivity: 30,
      scrollSpeed: 10,
      bubbleScroll: true
    };

    // Bind all private methods
    for (var fn in this) {
      if (fn.charAt(0) === '_' && typeof this[fn] === 'function') {
        this[fn] = this[fn].bind(this);
      }
    }
  }
  AutoScroll.prototype = {
    dragStarted: function dragStarted(_ref) {
      var originalEvent = _ref.originalEvent;
      if (this.sortable.nativeDraggable) {
        on(document, 'dragover', this._handleAutoScroll);
      } else {
        if (this.options.supportPointer) {
          on(document, 'pointermove', this._handleFallbackAutoScroll);
        } else if (originalEvent.touches) {
          on(document, 'touchmove', this._handleFallbackAutoScroll);
        } else {
          on(document, 'mousemove', this._handleFallbackAutoScroll);
        }
      }
    },
    dragOverCompleted: function dragOverCompleted(_ref2) {
      var originalEvent = _ref2.originalEvent;
      // For when bubbling is canceled and using fallback (fallback 'touchmove' always reached)
      if (!this.options.dragOverBubble && !originalEvent.rootEl) {
        this._handleAutoScroll(originalEvent);
      }
    },
    drop: function drop() {
      if (this.sortable.nativeDraggable) {
        off(document, 'dragover', this._handleAutoScroll);
      } else {
        off(document, 'pointermove', this._handleFallbackAutoScroll);
        off(document, 'touchmove', this._handleFallbackAutoScroll);
        off(document, 'mousemove', this._handleFallbackAutoScroll);
      }
      clearPointerElemChangedInterval();
      clearAutoScrolls();
      cancelThrottle();
    },
    nulling: function nulling() {
      touchEvt$1 = scrollRootEl = scrollEl = scrolling = pointerElemChangedInterval = lastAutoScrollX = lastAutoScrollY = null;
      autoScrolls.length = 0;
    },
    _handleFallbackAutoScroll: function _handleFallbackAutoScroll(evt) {
      this._handleAutoScroll(evt, true);
    },
    _handleAutoScroll: function _handleAutoScroll(evt, fallback) {
      var _this = this;
      var x = (evt.touches ? evt.touches[0] : evt).clientX,
        y = (evt.touches ? evt.touches[0] : evt).clientY,
        elem = document.elementFromPoint(x, y);
      touchEvt$1 = evt;

      // IE does not seem to have native autoscroll,
      // Edge's autoscroll seems too conditional,
      // MACOS Safari does not have autoscroll,
      // Firefox and Chrome are good
      if (fallback || this.options.forceAutoScrollFallback || Edge || IE11OrLess || Safari) {
        autoScroll(evt, this.options, elem, fallback);

        // Listener for pointer element change
        var ogElemScroller = getParentAutoScrollElement(elem, true);
        if (scrolling && (!pointerElemChangedInterval || x !== lastAutoScrollX || y !== lastAutoScrollY)) {
          pointerElemChangedInterval && clearPointerElemChangedInterval();
          // Detect for pointer elem change, emulating native DnD behaviour
          pointerElemChangedInterval = setInterval(function () {
            var newElem = getParentAutoScrollElement(document.elementFromPoint(x, y), true);
            if (newElem !== ogElemScroller) {
              ogElemScroller = newElem;
              clearAutoScrolls();
            }
            autoScroll(evt, _this.options, newElem, fallback);
          }, 10);
          lastAutoScrollX = x;
          lastAutoScrollY = y;
        }
      } else {
        // if DnD is enabled (and browser has good autoscrolling), first autoscroll will already scroll, so get parent autoscroll of first autoscroll
        if (!this.options.bubbleScroll || getParentAutoScrollElement(elem, true) === getWindowScrollingElement()) {
          clearAutoScrolls();
          return;
        }
        autoScroll(evt, this.options, getParentAutoScrollElement(elem, false), false);
      }
    }
  };
  return _extends(AutoScroll, {
    pluginName: 'scroll',
    initializeByDefault: true
  });
}
function clearAutoScrolls() {
  autoScrolls.forEach(function (autoScroll) {
    clearInterval(autoScroll.pid);
  });
  autoScrolls = [];
}
function clearPointerElemChangedInterval() {
  clearInterval(pointerElemChangedInterval);
}
var autoScroll = throttle(function (evt, options, rootEl, isFallback) {
  // Bug: https://bugzilla.mozilla.org/show_bug.cgi?id=505521
  if (!options.scroll) return;
  var x = (evt.touches ? evt.touches[0] : evt).clientX,
    y = (evt.touches ? evt.touches[0] : evt).clientY,
    sens = options.scrollSensitivity,
    speed = options.scrollSpeed,
    winScroller = getWindowScrollingElement();
  var scrollThisInstance = false,
    scrollCustomFn;

  // New scroll root, set scrollEl
  if (scrollRootEl !== rootEl) {
    scrollRootEl = rootEl;
    clearAutoScrolls();
    scrollEl = options.scroll;
    scrollCustomFn = options.scrollFn;
    if (scrollEl === true) {
      scrollEl = getParentAutoScrollElement(rootEl, true);
    }
  }
  var layersOut = 0;
  var currentParent = scrollEl;
  do {
    var el = currentParent,
      rect = getRect(el),
      top = rect.top,
      bottom = rect.bottom,
      left = rect.left,
      right = rect.right,
      width = rect.width,
      height = rect.height,
      canScrollX = void 0,
      canScrollY = void 0,
      scrollWidth = el.scrollWidth,
      scrollHeight = el.scrollHeight,
      elCSS = css(el),
      scrollPosX = el.scrollLeft,
      scrollPosY = el.scrollTop;
    if (el === winScroller) {
      canScrollX = width < scrollWidth && (elCSS.overflowX === 'auto' || elCSS.overflowX === 'scroll' || elCSS.overflowX === 'visible');
      canScrollY = height < scrollHeight && (elCSS.overflowY === 'auto' || elCSS.overflowY === 'scroll' || elCSS.overflowY === 'visible');
    } else {
      canScrollX = width < scrollWidth && (elCSS.overflowX === 'auto' || elCSS.overflowX === 'scroll');
      canScrollY = height < scrollHeight && (elCSS.overflowY === 'auto' || elCSS.overflowY === 'scroll');
    }
    var vx = canScrollX && (Math.abs(right - x) <= sens && scrollPosX + width < scrollWidth) - (Math.abs(left - x) <= sens && !!scrollPosX);
    var vy = canScrollY && (Math.abs(bottom - y) <= sens && scrollPosY + height < scrollHeight) - (Math.abs(top - y) <= sens && !!scrollPosY);
    if (!autoScrolls[layersOut]) {
      for (var i = 0; i <= layersOut; i++) {
        if (!autoScrolls[i]) {
          autoScrolls[i] = {};
        }
      }
    }
    if (autoScrolls[layersOut].vx != vx || autoScrolls[layersOut].vy != vy || autoScrolls[layersOut].el !== el) {
      autoScrolls[layersOut].el = el;
      autoScrolls[layersOut].vx = vx;
      autoScrolls[layersOut].vy = vy;
      clearInterval(autoScrolls[layersOut].pid);
      if (vx != 0 || vy != 0) {
        scrollThisInstance = true;
        /* jshint loopfunc:true */
        autoScrolls[layersOut].pid = setInterval(function () {
          // emulate drag over during autoscroll (fallback), emulating native DnD behaviour
          if (isFallback && this.layer === 0) {
            Sortable.active._onTouchMove(touchEvt$1); // To move ghost if it is positioned absolutely
          }
          var scrollOffsetY = autoScrolls[this.layer].vy ? autoScrolls[this.layer].vy * speed : 0;
          var scrollOffsetX = autoScrolls[this.layer].vx ? autoScrolls[this.layer].vx * speed : 0;
          if (typeof scrollCustomFn === 'function') {
            if (scrollCustomFn.call(Sortable.dragged.parentNode[expando], scrollOffsetX, scrollOffsetY, evt, touchEvt$1, autoScrolls[this.layer].el) !== 'continue') {
              return;
            }
          }
          scrollBy(autoScrolls[this.layer].el, scrollOffsetX, scrollOffsetY);
        }.bind({
          layer: layersOut
        }), 24);
      }
    }
    layersOut++;
  } while (options.bubbleScroll && currentParent !== winScroller && (currentParent = getParentAutoScrollElement(currentParent, false)));
  scrolling = scrollThisInstance; // in case another function catches scrolling as false in between when it is not
}, 30);

var drop = function drop(_ref) {
  var originalEvent = _ref.originalEvent,
    putSortable = _ref.putSortable,
    dragEl = _ref.dragEl,
    activeSortable = _ref.activeSortable,
    dispatchSortableEvent = _ref.dispatchSortableEvent,
    hideGhostForTarget = _ref.hideGhostForTarget,
    unhideGhostForTarget = _ref.unhideGhostForTarget;
  if (!originalEvent) return;
  var toSortable = putSortable || activeSortable;
  hideGhostForTarget();
  var touch = originalEvent.changedTouches && originalEvent.changedTouches.length ? originalEvent.changedTouches[0] : originalEvent;
  var target = document.elementFromPoint(touch.clientX, touch.clientY);
  unhideGhostForTarget();
  if (toSortable && !toSortable.el.contains(target)) {
    dispatchSortableEvent('spill');
    this.onSpill({
      dragEl: dragEl,
      putSortable: putSortable
    });
  }
};
function Revert() {}
Revert.prototype = {
  startIndex: null,
  dragStart: function dragStart(_ref2) {
    var oldDraggableIndex = _ref2.oldDraggableIndex;
    this.startIndex = oldDraggableIndex;
  },
  onSpill: function onSpill(_ref3) {
    var dragEl = _ref3.dragEl,
      putSortable = _ref3.putSortable;
    this.sortable.captureAnimationState();
    if (putSortable) {
      putSortable.captureAnimationState();
    }
    var nextSibling = getChild(this.sortable.el, this.startIndex, this.options);
    if (nextSibling) {
      this.sortable.el.insertBefore(dragEl, nextSibling);
    } else {
      this.sortable.el.appendChild(dragEl);
    }
    this.sortable.animateAll();
    if (putSortable) {
      putSortable.animateAll();
    }
  },
  drop: drop
};
_extends(Revert, {
  pluginName: 'revertOnSpill'
});
function Remove() {}
Remove.prototype = {
  onSpill: function onSpill(_ref4) {
    var dragEl = _ref4.dragEl,
      putSortable = _ref4.putSortable;
    var parentSortable = putSortable || this.sortable;
    parentSortable.captureAnimationState();
    dragEl.parentNode && dragEl.parentNode.removeChild(dragEl);
    parentSortable.animateAll();
  },
  drop: drop
};
_extends(Remove, {
  pluginName: 'removeOnSpill'
});

Sortable.mount(new AutoScrollPlugin());
Sortable.mount(Remove, Revert);

const CONFIG = {
	FORM_COMPONENTS: [
		{ type: "input", label: "Input" },
		{ type: "link", label: "Link" },
		{ type: "location", label: "Location" },
		{ type: "textarea", label: "Text" },
		{ type: "checkbox", label: "Checkbox" },
		{ type: "radio", label: "Radio Group" },
		{ type: "select", label: "Select" },
		{ type: "table", label: "Table" },
		{ type: "signature", label: "Signature" },
		{ type: "html", label: "Document" },
		{ type: "status", label: "Status" },
	],
	PAGE_COMPONENTS: [
		{ type: "input", label: "Input" },
		{ type: "link", label: "Link" },
		{ type: "location", label: "Location" },
		{ type: "textarea", label: "Text" },
		{ type: "bookmark", label: "Bookmark" },
		{ type: "checkbox", label: "Checkbox" },
		{ type: "radio", label: "Radio Group" },
		{ type: "select", label: "Select" },
		{ type: "table", label: "Table" },
	],
	INPUTS: [
		{ type: "text", name: "Text" },
		{ type: "tel", name: "Phone Number" },
		{ type: "number", name: "Number" },
		{ type: "email", name: "Email" },
		{ type: "date", name: "Date" },
		{ type: "time", name: "Time" },
	],
	TABLE_COLUMNS: [
		{ type: "text", name: "Text" },
		{ type: "tel", name: "Phone Number" },
		{ type: "number", name: "Number" },
		{ type: "email", name: "Email" },
		{ type: "date", name: "Date" },
		{ type: "time", name: "Time" },
		{ type: "out", name: "External Link" },
		{ type: "in", name: "Internal Link" },
		{ type: "checkbox", name: "Checkbox" },
	],
	LINKS: [
		{ type: "out", name: "External" },
		{ type: "in", name: "Internal" },
	],
	PRESENTATION_DEFAULTS: {
		bookmark: { title: "Bookmark" },
		checkbox: { title: "Checkbox" },
		html: { title: "Rich Text" },
		input: { title: "Input", input: "text" },
		link: { title: "Link", location: "out" },
		location: { title: "Location" },
		radio: { title: "Radio Group" },
		select: { title: "Select" },
		signature: { title: "Signature" },
		status: { title: "Status" },
		table: { title: "Table" },
		textarea: { title: "Text" },
	},
	DEFAULT_SETTINGS: {
		input: [
			"title",
			"placeholder",
			"visibility",
			"input",
			"required",
			"deleteButton",
		],
		link: ["title", "visibility", "required", "location", "deleteButton"],
		location: [
			"title",
			"placeholder",
			"visibility",
			"required",
			"deleteButton",
		],
		textarea: [
			"title",
			"placeholder",
			"visibility",
			"required",
			"deleteButton",
		],
		bookmark: ["title", "deleteButton"],
		checkbox: ["title", "visibility", "checked", "required", "deleteButton"],
		radio: ["title", "visibility", "options", "required", "deleteButton"],
		select: [
			"title",
			"placeholder",
			"visibility",
			"options",
			"multiple",
			"required",
			"deleteButton",
		],
		html: ["title", "visibility", "editor", "deleteButton"],
		signature: ["title", "required", "deleteButton"],
		status: ["title", "status", "deleteButton"],
		table: ["title", "columns", "visibility", "deleteButton"],
	},
};

/**
 * @testable infrastructure
 */
class ComponentsPanel {
	constructor(builder) {
		this.builder = builder;
		this.column = document.getElementById("components-column");
		this.panel = document.getElementById("components-panel");
		this._click = this._click.bind(this);
		this._move = this._move.bind(this);
		this.init();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
	 * @features forms
	 * @dimensions page-form task-form components
	 */
	init() {
		const componentConfig =
			this.builder.elt.dataset.formType === "page"
				? CONFIG.PAGE_COMPONENTS
				: CONFIG.FORM_COMPONENTS;

		const components = [];

		componentConfig.forEach(({ type, label }) => {
			const component = document.createElement("div");
			component.className = `${STYLES.builder.component}`;
			component.dataset.type = type;

			const icon = component.appendChild(document.createElement("span"));
			setIcon(icon, type, "text-form-default");

			const name = component.appendChild(document.createElement("span"));
			name.textContent = label;

			const addButton = component.appendChild(document.createElement("button"));
			addButton.dataset.role = "add";
			addButton.type = "button";
			addButton.title = `Add ${label}`;
			addButton.setAttribute("aria-label", `Add ${label}`);
			addButton.className =
				"ml-auto grid size-6 place-items-center rounded-md text-form-default hover:bg-white hover:outline-2 hover:outline-form-default focus-visible:bg-white focus-visible:outline-2 focus-visible:outline-form-default";

			const addIcon = addButton.appendChild(document.createElement("span"));
			setIcon(addIcon, "plus");

			components.push(component);
		});

		this.panel.append(...components);

		this.sortable = Sortable.create(this.panel, {
			group: {
				name: "builder",
				pull: "clone",
				put: false,
			},
			onMove: this._move,
			animation: 150,
			sort: false,
		});

		this.column.addEventListener("click", this._click);
	}

	_move(event) {
		const type = event.dragged.dataset.type;
		if (this.builder.model.hasUniqueElement(type)) {
			this.builder.header.message(
				`Only one ${type} element is allowed per form`,
			);
			return false;
		}

		return true;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_add_inputs_to_form
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_add_fields_to_form
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_signature_field_builder_unique_component
	 * @features forms
	 * @dimensions builder-add-inputs builder-add-fields unique-component
	 */
	_click(event) {
		const button = event.target.closest("[data-role]");
		if (button?.dataset.role === "add") {
			const type = button.closest("[data-type]").dataset.type;
			if (this.builder.model.hasUniqueElement(type)) {
				this.builder.header.message(
					`Only one ${type} element is allowed per form`,
				);
				return;
			}

			const element = this.builder.createElement({ type });
			this.builder.model.sortable.el.appendChild(element);
			this.builder.updateSchemaOrder();
			this.builder.selectElement(element.id);
		}
	}

	destroy() {
		this.sortable.destroy();
	}
}

/**
 * @testable infrastructure
 */
class ConditionPanel {
	constructor(builder) {
		this.builder = builder;
		this.panel = document.getElementById("condition-panel");
		this.loading = false;
		this.condition = null;
		this.init();
	}

	init() {
		this.panel.addEventListener("click", (e) => {
			const button = e.target.closest("button");
			if (button?.dataset.role === "save") {
				const validated = this.condition.validate();
				if (!validated) return;

				const index = this.condition.index;
				const schema = this.condition.element.schema;
				const conditions = schema[this.condition.key] ?? [];

				if (index === -1) {
					conditions.push(this.condition.setting);
				} else {
					conditions[index] = this.condition.setting;
				}

				schema[this.condition.key] = conditions;
				this.condition.element.settings = this.builder.settings.create(schema);
				this.builder.updateSchema();

				withTransition(() => {
					this.condition.index = -1;
					this.condition.init();
					this.condition.showSuccess();
					this.condition.focus();
					this.builder.settings.updateItem();
					this.builder.model.updateItem();
				});
			} else if (button?.dataset.role === "close") {
				this.close();
			}
		});
	}

	open(condition) {
		this.builder.model.sortable.option("disabled", true);
		this.builder.components.sortable.option("disabled", true);
		this.builder.model.focusItem();

		if (condition.expand) {
			this.builder.elt.dataset.expanded = "true";
		}

		this.panel.replaceChildren(condition.target);
		this.panel.dataset.visible = "true";
		this.condition = condition;
		this.loading = false;
	}

	hide() {
		this.builder.model.sortable.option("disabled", false);
		this.builder.components.sortable.option("disabled", false);
		this.builder.model.blurItem();
		this.panel.dataset.visible = "false";
		this.condition = null;
	}

	close() {
		withTransition(() => {
			this.hide();
			this.builder.elt.dataset.expanded = "false";
		});
	}
}

/**
 * @testable infrastructure
 */
const _section = (name, elements) => {
	const section = document.createElement("div");
	section.className = STYLES.builder.settings.section;
	section.append(...elements.filter(Boolean));
	section.dataset.setting = name;
	return section;
};

/**
 * @testable infrastructure
 */
const _presentation$1 = (schema) => {
	const defaults = CONFIG.PRESENTATION_DEFAULTS[schema.type] || {};
	return {
		title: schema.title ?? defaults.title,
		input: schema.input ?? defaults.input,
		location: schema.location ?? defaults.location,
	};
};

/**
 * @testable infrastructure
 */
const _toggle = (icon, role, kind = "form", disabled = false) => {
	const toggle = primitives.toggle({
		icon: icon,
		styles: {
			container: STYLES.builder.settings.toggle.container,
			icon: STYLES.builder.settings.toggle.icon,
		},
		data: {
			role: role,
		},
	});
	toggle.dataset.kind = kind;
	if (disabled) {
		toggle.disabled = true;
		toggle.classList.add("opacity-50", "pointer-events-none");
	}
	return toggle;
};

/**
 * @testable infrastructure
 */
const _condition = (condition, index) => {
	const elt = document.createElement("li");
	elt.className = STYLES.builder.settings.item;
	elt.dataset.index = index;

	const wrapper = document.createElement("div");
	wrapper.className = `sm:text-sm hover:underline`;
	wrapper.dataset.role = "open";

	const target = wrapper.appendChild(document.createElement("span"));
	target.textContent = condition.name;
	target.className = `font-semibold text-form-dark`;

	const text = wrapper.appendChild(document.createElement("span"));
	text.className = `italic text-base-dark`;
	text.textContent = condition.checked ? " is " : " has the value ";

	const status = wrapper.appendChild(document.createElement("span"));
	status.className = `font-semibold text-project-default`;
	status.textContent = condition.checked ? "checked" : condition.label;

	const remove = _toggle("x", "remove", "delete");

	elt.append(wrapper, remove);
	return elt;
};

/**
 * @testable infrastructure
 */
const _option = (option, index, length) => {
	const wrapper = document.createElement("li");
	wrapper.className = STYLES.builder.settings.item;
	wrapper.dataset.index = index;

	const name = wrapper.appendChild(document.createElement("span"));
	name.textContent = option.label;
	name.className = `sm:text-sm hover:underline`;
	name.dataset.role = "open";

	const toggles = document.createElement("div");
	toggles.className = `flex flex-row gap-1`;
	if (length > 1) {
		toggles.appendChild(
			_toggle("down", "moveDown", "form", index === length - 1),
		);
		toggles.appendChild(_toggle("up", "moveUp", "form", index === 0));
	}
	toggles.appendChild(_toggle("x", "remove", "delete"));

	wrapper.append(name, toggles);

	return wrapper;
};

/**
 * @testable infrastructure
 */
const _column = (column, index, length) => {
	const wrapper = document.createElement("div");
	wrapper.className = STYLES.builder.settings.item;
	wrapper.dataset.index = index;

	const name = primitives.label({
		icon: column.location || column.input || column.type,
		label: column.name || column.title,
		tag: "h3",
		role: "open",
		styles: {
			container: "flex flex-row items-center gap-1.5",
		},
	});
	name.className = `sm:text-sm hover:underline`;

	const toggles = document.createElement("div");
	toggles.className = `flex flex-row gap-1`;
	if (length > 1) {
		toggles.appendChild(
			_toggle("down", "moveDown", "form", index === length - 1),
		);
		toggles.appendChild(_toggle("up", "moveUp", "form", index === 0));
	}
	toggles.appendChild(_toggle("x", "remove", "delete"));

	wrapper.append(name, toggles);
	return wrapper;
};

/**
 * @testable infrastructure
 */
const title = (schema) => {
	const title = primitives.input({
		label: "Title",
		name: "title",
		value: _presentation$1(schema).title,
	});
	return _section("title", [title]);
};

/**
 * @testable infrastructure
 */
const placeholder = (schema) => {
	const placeholder = primitives.input({
		label: "Placeholder",
		name: "placeholder",
		value: schema.placeholder || "",
	});
	return _section("placeholder", [placeholder]);
};

/**
 * @testable infrastructure
 */
const visibility = (schema) => {
	const title = document.createElement("div");
	title.className = STYLES.builder.settings.title;
	const label = primitives.label({
		label: "Visibility",
		tag: "h3",
	});
	const toggle = _toggle("plus", "add");
	title.append(label, toggle);

	if (schema.visibility) {
		const visibilityList = document.createElement("ul");
		visibilityList.className = `flex flex-col gap-1`;
		schema.visibility.forEach((condition, index) => {
			visibilityList.appendChild(_condition(condition, index));
		});
		return _section("visibility", [title, visibilityList]);
	}
	return _section("visibility", [title]);
};

/**
 * @testable infrastructure
 */
const status$1 = (schema) => {
	const title = document.createElement("div");
	title.className = STYLES.builder.settings.title;
	const label = primitives.label({
		label: "Status",
		tag: "h3",
	});
	const toggle = _toggle("plus", "add");
	title.append(label, toggle);

	if (schema.status) {
		const statusList = document.createElement("ul");
		statusList.className = `flex flex-col gap-1`;
		schema.status.forEach((status, index) => {
			statusList.appendChild(_condition(status, index));
		});
		return _section("status", [title, statusList]);
	} else {
		return _section("status", [title]);
	}
};

/**
 * @testable infrastructure
 */
const options = (schema) => {
	const title = document.createElement("div");
	title.className = STYLES.builder.settings.title;
	const label = primitives.label({
		label: "Options",
		tag: "h3",
	});
	const toggle = _toggle("plus", "add");
	title.append(label, toggle);

	if (schema.options) {
		const optionList = document.createElement("ul");
		optionList.className = `flex flex-col gap-1`;
		const length = schema.options.length;
		schema.options.forEach((option, index) => {
			optionList.appendChild(_option(option, index, length));
		});
		return _section("options", [title, optionList]);
	} else {
		return _section("options", [title]);
	}
};

/**
 * @testable infrastructure
 */
const editor = () => {
	const title = document.createElement("div");
	title.className = STYLES.builder.settings.title;
	const label = primitives.label({
		label: "Editor",
		tag: "h3",
	});
	const toggle = _toggle("edit", "edit");
	title.append(label, toggle);
	return _section("html", [title]);
};

/**
 * @testable infrastructure
 */
const input$1 = (schema) => {
	const display = _presentation$1(schema);
	const fieldset = document.createElement("fieldset");
	fieldset.className = STYLES.radio.fieldset.column;
	fieldset.dataset.kind = "base";

	const legend = fieldset.appendChild(document.createElement("legend"));
	legend.textContent = "Input Type";
	legend.className = `${STYLES.label.sectionHeading}`;

	CONFIG.INPUTS.forEach((type) => {
		fieldset.appendChild(
			primitives.radio({
				icon: type.type,
				label: type.name,
				name: "input",
				value: type.type,
				checked: type.type === display.input,
			}),
		);
	});

	return _section("input", [fieldset]);
};

/**
 * @testable infrastructure
 */
const location$1 = (schema) => {
	const display = _presentation$1(schema);
	const fieldset = document.createElement("fieldset");
	fieldset.className = STYLES.radio.fieldset.column;
	fieldset.dataset.kind = "form";

	const legend = fieldset.appendChild(document.createElement("legend"));
	legend.textContent = "Link Type";
	legend.className = `${STYLES.label.sectionHeading}`;

	CONFIG.LINKS.forEach((type) => {
		fieldset.appendChild(
			primitives.radio({
				icon: type.type,
				label: type.name,
				name: "location",
				value: type.type,
				checked: type.type === display.location,
			}),
		);
	});

	return _section("location", [fieldset]);
};

/**
 * @testable infrastructure
 */
const columns = (schema) => {
	const title = document.createElement("div");
	title.className = STYLES.builder.settings.title;
	const label = primitives.label({
		label: "Columns",
		tag: "h3",
	});
	const toggle = _toggle("plus", "add");
	title.append(label, toggle);

	if (schema.columns) {
		const columnList = document.createElement("ul");
		columnList.className = `flex flex-col gap-1`;
		const length = schema.columns.length;
		schema.columns.forEach((column, index) => {
			columnList.appendChild(_column(column, index, length));
		});
		return _section("columns", [title, columnList]);
	} else {
		return _section("columns", [title]);
	}
};

/**
 * @testable infrastructure
 */
const required = (schema) => {
	const required = primitives.checkbox({
		label: "Required",
		name: "required",
		checked: !!schema.required,
	});
	return _section("required", [required]);
};

/**
 * @testable infrastructure
 */
const multiple = (schema) => {
	const multiple = primitives.checkbox({
		label: "Multiple",
		name: "multiple",
		checked: !!schema.multiple,
	});
	return _section("multiple", [multiple]);
};

/**
 * @testable infrastructure
 */
const checked = (schema) => {
	const checked = primitives.checkbox({
		label: "Default",
		name: "checked",
		checked: !!schema.checked,
	});
	return _section("checked", [checked]);
};

/**
 * @testable infrastructure
 */
const deleteButton = () => {
	const button = document.createElement("button");
	button.textContent = "Delete";
	button.dataset.kind = "delete";
	button.dataset.role = "delete";
	button.className = `${STYLES.button.submit}`;
	return button;
};

const SettingsElement = {
	title: title,
	placeholder: placeholder,
	visibility: visibility,
	status: status$1,
	options: options,
	input: input$1,
	location: location$1,
	columns: columns,
	required: required,
	multiple: multiple,
	checked: checked,
	editor: editor,
	deleteButton: deleteButton,
};

/**
 * @testable infrastructure
 */
class ElementSettings {
	constructor(builder) {
		this.builder = builder;
		this.panel = document.getElementById("settings-panel");
		this._input = this._input.bind(this);
		this._change = this._change.bind(this);
		this._click = this._click.bind(this);
		this._blur = this._blur.bind(this);
	}

	init() {
		this.panel.addEventListener("input", this._input);
		this.panel.addEventListener("change", this._change);
		this.panel.addEventListener("click", this._click);
		this.panel.addEventListener("blur", this._blur);
	}

	_input(e) {
		const element = this.builder.selectedElement;
		if (e.target.closest("[data-setting=title]")) {
			this._setTitle(element, e.target.value);
		} else if (e.target.closest("[data-setting=placeholder]")) {
			this._setPlaceholder(element, e.target.value);
		}
	}

	_change(e) {
		const element = this.builder.selectedElement;
		if (e.target.closest("[data-setting=required]")) {
			this._setRequired(element, e.target.checked);
		} else if (e.target.closest("[data-setting=checked]")) {
			this._setChecked(element, e.target.checked);
		} else if (e.target.closest("[data-setting=multiple]")) {
			this._setMultiple(element, e.target.checked);
		} else if (e.target.closest("[data-setting=input]")) {
			this._setInput(element, e.target.value);
		} else if (e.target.closest("[data-setting=location]")) {
			this._setLocation(element, e.target.value);
		}
		this.builder.updateSchema();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_change_select_options
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_field_visibility
	 * @features forms
	 * @dimensions builder-select-options builder-field-visibility
	 */
	_click(e) {
		const element = this.builder.selectedElement;
		const role = e.target.closest("[data-role]")?.dataset.role;
		const setting = e.target.closest("[data-index]");
		const index = setting ? parseInt(setting.dataset.index, 10) : -1;
		const name = e.target.closest("[data-setting]")?.dataset.setting;

		if (role === "remove") {
			this._removeSchemaListItem(element.schema[name], index);
		} else if (["moveUp", "moveDown"].includes(role)) {
			this._moveSchemaListItem(element, name, index, role);
		} else if (["add", "edit", "open"].includes(role)) {
			this.builder.showCondition(name, index);
		} else if (role === "delete") {
			this.builder.removeElement();
			this.deselectItem();
			this.builder.formSettings.visible = true;
		}
	}

	_blur() {
		this.builder.updateSchema();
	}

	_removeSchemaListItem(schema, index) {
		schema.splice(index, 1);
		this.builder.updateSchema();
		withTransition(() => {
			this.builder.model.updateItem();
			this.builder.selectedElement.settings = this.create(
				this.builder.selectedElement.schema,
			);
			this.updateItem();
		});
	}

	_moveSchemaListItem(element, name, index, direction) {
		const arr = element.schema[name];
		const newIndex = direction === "moveUp" ? index - 1 : index + 1;
		if (newIndex < 0 || newIndex >= arr.length) return;
		[arr[index], arr[newIndex]] = [arr[newIndex], arr[index]];
		this.builder.updateSchema();
		withTransition(() => {
			this.builder.model.updateItem();
			this.builder.selectedElement.settings = this.create(
				this.builder.selectedElement.schema,
			);
			this.updateItem();
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_change_select_options
	 * @pairs forms:builder-field-title frontend-icons:material-icon-preservation
	 */
	_setTitle(element, value) {
		element.schema.title = value;
		element.item.querySelector(
			"[data-role='label'] > span:not([data-icon])",
		).textContent = value;
	}

	_setPlaceholder(element, value) {
		element.schema.placeholder = value;
		const input = element.item.querySelector("input, textarea");
		if (input) input.placeholder = value;
	}

	_setRequired(element, value) {
		element.schema.required = value;
	}

	_setChecked(element, value) {
		element.schema.checked = value;
		element.item.querySelector("input[type='checkbox']").checked = value;
	}

	_setMultiple(element, value) {
		element.schema.multiple = value;
	}

	_setInput(element, value) {
		element.schema.input = value;
		const label = primitives.label({
			icon: value,
			label: _presentation$1(element.schema).title,
		});
		element.item
			.querySelector("label > div")
			.replaceWith(label.querySelector("div"));
	}

	_setLocation(element, value) {
		element.schema.location = value;
		const label = primitives.label({
			icon: value,
			label: _presentation$1(element.schema).title,
			tag: "h3",
		});
		element.item.querySelector("h3").replaceWith(label);
	}

	create(schema) {
		const settings = CONFIG.DEFAULT_SETTINGS[schema.type].map((setting) => {
			if (
				["name", "description"].includes(schema.id) &&
				setting === "deleteButton"
			) {
				return null;
			}
			return SettingsElement[setting](schema);
		});
		return settings.filter(Boolean);
	}

	selectItem() {
		const item = this.builder.selectedElement;
		this.panel.replaceChildren(...item.settings);
		this.panel.dataset.visible = "true";
		this.builder.formSettings.visible = false;
	}

	deselectItem() {
		this.panel.dataset.visible = "false";
	}

	updateItem() {
		this.panel.dataset.visible = "false";
		const item = this.builder.selectedElement;
		this.panel.replaceChildren(...item.settings);
		this.panel.dataset.visible = "true";
	}
}

/**
 * @testable infrastructure
 */
class FormSettings {
	constructor(builder) {
		this.builder = builder;
		this.column = document.getElementById("form-settings-panel");
		this.restrictions = document.querySelector("[data-role='restrict-access']");
		this.selectGroup = null;

		const generateTarget = this.column?.querySelector("#generate");
		if (generateTarget) {
			this.generateForm = new BaseForm({
				target: generateTarget,
				submitGroup: generateTarget.querySelector("[data-role='submit-group']"),
				messages: {
					submit: "Generate",
					submitting: "Thinking...",
					submitted: "Generated",
				},
			});
		} else {
			this.generateForm = null;
		}

		this._generateSchema = this._generateSchema.bind(this);
		this._addRestriction = this._addRestriction.bind(this);
		this._input = this._input.bind(this);
		this._click = this._click.bind(this);
	}

	/**
	 * @testable true
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_group
	 * @features forms
	 * @dimensions access-restrictions group-restricted
	 */
	init() {
		if (this.generateForm) {
			this.generateForm.init();
			this.generateForm.target.addEventListener("submit", this._generateSchema);
		}

		this.column?.addEventListener("input", this._input);
		this.column?.addEventListener("click", this._click);

		if (this.restrictions) {
			const input = this.column.querySelector(
				"[data-role='restrict-group-input']",
			);
			this.selectGroup = new FacetsBox(input);
			this.selectGroup.init();
			this.restrictions.addEventListener("updated", (event) => {
				const data = new FormData();
				data.set("action", "add");

				Object.keys(event.detail.options).forEach((key) => {
					data.append("group-key", key);
				});
				this._addRestriction(data);
			});
		}
	}

	/**
	 * @testable true
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_owner
	 * @features forms
	 * @dimensions access-restrictions owner-restricted
	 */
	_input(event) {
		if (event.target.name === "description" && this.generateForm?.target) {
			const explain = this.generateForm.target.querySelector(
				"[data-role='explain']",
			);
			if (explain) explain.dataset.visible = "true";
		} else if (event.target.dataset.role === "specific-access") {
			const data = new FormData();
			data.set("action", event.target.checked ? "add" : "remove");
			data.set("specific", event.target.name);
			this._addRestriction(data);
		}
	}

	_click(event) {
		const button = event.target.closest("[data-role]");
		if (button?.dataset.role === "generate" && this.generateForm?.target) {
			const visible = this.generateForm.target.dataset.visible === "true";
			this.generateForm.target.dataset.visible = visible ? "false" : "true";
			if (!visible) this.generateForm.target.querySelector("textarea")?.focus();
		} else if (button?.dataset.role === "cancel" && this.generateForm?.target) {
			this.generateForm.target.dataset.visible = "false";
			this.generateForm.resetSubmitButton();
			const ta = this.generateForm.target.querySelector("textarea");
			if (ta) ta.value = "";
		} else if (button?.dataset.role === "remove-restriction") {
			this._removeRestriction(button);
		}
	}

	get visible() {
		return this.column.dataset.visible === "true";
	}

	set visible(value) {
		this.column.dataset.visible = value ? "true" : "false";
	}

	/**
	 * @testable true
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_owner
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_group
	 * @features forms
	 * @dimensions access-restrictions owner-restricted group-restricted
	 */
	async _addRestriction(data) {
		if (!this.restrictions) return;

		const route = this.restrictions.dataset.route;

		const response = await request.put(route, data);
		if (response.html) {
			const list = this.restrictions.querySelector("ul");
			const nodes =
				typeof response.html === "string"
					? null
					: Array.from(response.html.body.children);

			if (nodes?.length) {
				list?.append(...nodes.map((node) => document.importNode(node, true)));
			} else if (typeof response.html === "string") {
				list?.insertAdjacentHTML("beforeend", response.html);
			}
		}
		this.selectGroup?.clear({ notify: false });
	}

	async _removeRestriction(button) {
		if (!this.restrictions) return;

		const route = this.restrictions.dataset.route;
		const key = button.dataset.key;
		const item = button.closest("li");
		item.classList.add("opacity-50", "pointer-events-none");

		const data = new FormData();
		data.set("action", "remove");
		data.set("group-key", key);

		const response = await request.put(route, data);
		if (response.ok) {
			item.remove();
		}
	}

	async _generateSchema(event) {
		if (!this.generateForm?.target) return;

		event.preventDefault();
		event.stopPropagation();

		const data = new FormData(this.generateForm.target);
		const prompt = data.get("description");
		event.submitter.disabled = true;

		if (!prompt) {
			this.generateForm.showError("Please enter a description");
			return;
		} else if (event.submitter.dataset.explain) {
			data.append("explain", event.submitter.dataset.explain);
		}

		const response = await request.post(ENDPOINTS.createSchema, data);
		const success = await this._updateSchema(response);

		event.submitter.disabled = false;
		this.generateForm.resetSubmitButton();

		if (success) {
			this.generateForm.target.dataset.visible = "false";
		}
	}

	async _updateSchema(response) {
		if (!this.generateForm) return false;

		if (response.ok && response.schema) {
			if (response.schema.length === 0) {
				this.generateForm.showError("No form elements generated");
				return;
			}

			for (const element of response.schema) {
				if (this.builder.elements.get(element.id)) continue;
				const newElement = await this.builder.createElement(element);
				this.builder.model.panel.appendChild(newElement);
			}
			this.builder.updateSchemaOrder();
			this.builder.header.saved();
			return true;
		} else if (response.ok && response.modal) {
			const modal = new Modal(this.builder);
			modal.attach(response.modal, this.generateForm);
		} else if (response.error) {
			this.generateForm.showError(response.error);
		}
		return false;
	}

	destroy() {
		this.generateForm?.destroy();
		this.selectGroup?.destroy();
	}
}

/**
 * @testable infrastructure
 */
class Header {
	constructor(builder) {
		this.builder = builder;
		this.nameDisplay = document.getElementById("form-name-display");
		this.nameInput = document.getElementById("form-name-input");
		this.nameHidden = document.getElementById("form-name-hidden");
		this.saveButton = document.querySelector("[data-saved]");
		this.schemaForm = document.getElementById("schema-form");
		this.notification = document.getElementById("notification");
		this.previewToggle = document.getElementById("preview-toggle");
		this.previewPanel = document.getElementById("preview-panel");

		this.togglePreviewPanel = this.togglePreviewPanel.bind(this);
		this.saveForm = this.saveForm.bind(this);
		this.editFormName = this.editFormName.bind(this);
		this._nameBlur = this._nameBlur.bind(this);
		this._nameKeyDown = this._nameKeyDown.bind(this);

		this.renderer = null;

		this.init();
	}

	init() {
		this.nameInput.addEventListener("blur", this._nameBlur);
		this.nameInput.addEventListener("keydown", this._nameKeyDown);
	}

	saved() {
		if (!this.saveButton) return;
		this.saveButton.disabled = false;
		this.saveButton.classList.remove("opacity-50");
		this.saveButton.dataset.saved = "true";
		this.saveButton.dataset.kind = "saved";
	}

	unsaved() {
		if (!this.saveButton) return;
		this.saveButton.dataset.saved = "false";
		this.saveButton.dataset.kind = "unsaved";
	}

	message(text) {
		this.notification.textContent = text;
		this.notification.dataset.visible = "true";
		setTimeout(() => {
			this.notification.dataset.visible = "false";
		}, 3000);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_preview_panel
	 * @features forms
	 * @dimensions builder-preview
	 */
	async togglePreviewPanel() {
		const active = this.previewToggle.dataset.active === "true";
		this.previewToggle.dataset.active = active ? "false" : "true";
		this.previewToggle.setAttribute("aria-checked", active ? "false" : "true");

		let renderer = null;
		if (!active) {
			renderer = new Renderer({
				target: this.previewPanel,
				schema: this.builder.schema,
				kind: "form",
				key: this.builder.key,
				submission: {},
			});
			await renderer.render();
		}

		await withTransition(
			() => {
				if (!active) {
					this.renderer = renderer;
					this.builder.elt.dataset.expanded = "true";
					this.previewPanel.dataset.visible = "true";
					this.builder.conditions.hide();
					this.builder.model.hide();
				} else {
					this.renderer.destroy();
					this.renderer = null;
					this.builder.elt.dataset.expanded = "false";
					this.previewPanel.dataset.visible = "false";
					this.builder.model.show();
				}
			},
			{ label: "builder:toggle-preview" },
		);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_add_inputs_to_form
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_add_fields_to_form
	 * @features forms
	 * @dimensions builder-save builder-reload
	 */
	async saveForm() {
		if (!this.saveButton || !this.schemaForm) return;
		this.saveButton.disabled = true;
		this.saveButton.classList.add("opacity-50");
		const response = await request.put(
			this.schemaForm.dataset.route,
			new FormData(this.schemaForm),
		);
		response.ok ? this.saved() : this.message(response.error);
	}

	editFormName() {
		this.nameDisplay.dataset.visible = "false";
		this.nameInput.dataset.visible = "true";
		this.nameInput.focus();
		this.nameInput.select();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_copy_form_from_builder_title_menu
	 * @pairs forms:builder-form-name entity-menu:title-menu
	 * @pairs frontend-icons:material-icon-preservation
	 */
	_nameBlur() {
		const newName = this.nameInput.value.trim();
		if (newName !== this.nameDisplay.textContent) {
			this.nameDisplay.textContent = newName;
			this.nameHidden.value = newName;
			this.unsaved();
		}
		this.nameInput.dataset.visible = "false";
		this.nameDisplay.dataset.visible = "true";
	}

	_nameKeyDown(e) {
		if (e.key === "Enter") {
			e.preventDefault();
			this.nameInput.blur();
		} else if (e.key === "Escape") {
			this.nameInput.value = this.nameDisplay.textContent;
			this.nameInput.blur();
		}
	}

	destroy() {
		this.renderer?.destroy();
		this.renderer = null;
	}
}

/**
 * @testable infrastructure
 */
class ModelPanel {
	constructor(builder) {
		this.builder = builder;
		this.panel = document.getElementById("model-panel");
		this.defaultPanel = document.getElementById("default-panel");
		this.uniqueElements = ["status", "signature", "bookmark"];
		this.defaultElements = ["name", "description"];
		this._addElement = this._addElement.bind(this);
		this._moveElement = this._moveElement.bind(this);
	}

	get elements() {
		return Array.from(this.panel.querySelectorAll(".form-element"));
	}

	get defaults() {
		return Array.from(this.defaultPanel.querySelectorAll(".form-element"));
	}

	show() {
		this.defaultPanel.dataset.visible =
			this.defaults.length > 0 ? "true" : "false";
		this.panel.dataset.visible = "true";
	}

	hide() {
		this.defaultPanel.dataset.visible = "false";
		this.panel.dataset.visible = "false";
	}

	init() {
		const elements = Array.from(this.builder.elements.values());
		const defaults = elements.filter((element) =>
			this.defaultElements.includes(element.schema.id),
		);
		if (defaults.length > 0) {
			this.defaultPanel.dataset.visible = "true";
		}

		elements.forEach((element) => {
			if (this.defaultElements.includes(element.schema.id)) {
				Array.from(element.item.querySelectorAll("input, textarea")).forEach(
					(input) => {
						input.remove();
					},
				);
				this.defaultPanel.appendChild(element.item);
			} else {
				this.panel.appendChild(element.item);
			}
		});

		this.sortable = Sortable.create(this.panel, {
			group: {
				name: "builder",
				pull: false,
				put: true,
			},
			animation: 150,
			onAdd: this._addElement,
			onUpdate: this._moveElement,
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_drag_component
	 * @features forms
	 * @dimensions builder-drag-component
	 */
	_addElement(event) {
		const item = this.builder.createElement({
			type: event.item.dataset.type,
		});
		event.item.remove();
		event.to.insertBefore(item, event.to.children[event.newDraggableIndex]);
		this.builder.updateSchemaOrder();
		this.builder.selectElement(item.id);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_drag_component
	 * @features forms
	 * @dimensions builder-drag-component
	 */
	_moveElement() {
		this.builder.updateSchemaOrder();
	}

	updateItem() {
		const element = this.builder.selectedElement;
		const item = ModelElement[element.schema.type](element.schema);
		element.item.replaceWith(item);
		element.item = item;
		this.selectItem();
	}

	selectItem() {
		const selected = this.builder.selectedElement.item;

		this.elements.forEach((element) => {
			element.dataset.selected = element === selected ? "true" : "false";
		});
		this.defaults.forEach((element) => {
			element.dataset.selected = element === selected ? "true" : "false";
		});
	}

	deselectItem() {
		this.builder.selectedElement.item.dataset.selected = "false";
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_signature_field_builder_unique_component
	 * @features forms signature
	 * @dimensions unique-component
	 */
	hasUniqueElement(type) {
		return (
			this.uniqueElements.includes(type) &&
			this.panel.querySelector(`[id^="${type}"]`)
		);
	}

	focusItem() {
		const selected = this.builder.selectedElement.item;
		this.elements.forEach((element) => {
			element.dataset.visible = element === selected ? "true" : "false";
		});
		this.panel.classList.remove("min-h-[300px]");
		this.defaultPanel.dataset.visible = "false";
	}

	blurItem() {
		this.elements.forEach((element) => {
			element.dataset.visible = "true";
		});
		if (this.defaultPanel.children.length > 0) {
			this.defaultPanel.dataset.visible = "true";
		}
		this.panel.classList.add("min-h-[300px]");
	}

	destroy() {
		this.sortable.destroy();
	}
}

/**
 * @testable infrastructure
 */
const _model = (schema) => {
	const element = document.createElement("div");
	element.id = schema.id;
	element.dataset.selected = "false";
	element.dataset.visible = "true";
	element.className = `${STYLES.builder.model}`;
	return element;
};

/**
 * @testable true
 * @tests tests_js/test_019_form_sync_frontend.py::test_builder_model_defaults_are_presentation_only
 * @features forms form-schema
 * @dimensions builder presentation-defaults immutable-schema
 */
const _presentation = (schema) => {
	const defaults = CONFIG.PRESENTATION_DEFAULTS[schema.type] || {};
	return {
		...schema,
		title: schema.title ?? defaults.title,
		input: schema.input ?? defaults.input,
		location: schema.location ?? defaults.location,
	};
};

/**
 * @testable infrastructure
 */
const checkbox = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-row", "gap-2");

	element.appendChild(
		primitives.checkbox({
			label: display.title,
			checked: !!schema.checked,
			name: schema.id,
			disabled: true,
		}),
	);

	return element;
};

/**
 * @testable infrastructure
 */
const html = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	const label = primitives.label({
		icon: "html",
		label: display.title,
		tag: "h3",
	});
	element.appendChild(label);
	return element;
};

/**
 * @testable infrastructure
 */
const input = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-col", "gap-1");

	const input = primitives.input({
		icon: display.input,
		label: display.title,
		name: schema.id,
		type: display.input,
		disabled: true,
		placeholder: schema.placeholder,
	});

	element.appendChild(input);
	return element;
};

/**
 * @testable infrastructure
 */
const link = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	let linkElt;
	if (display.location === "out") {
		linkElt = primitives.label({
			icon: display.location,
			label: display.title,
			tag: "h3",
		});
	} else {
		linkElt = primitives.select({
			label: display.title,
			icon: display.location,
			selectIcon: "search",
			disabled: true,
		});
	}

	element.appendChild(linkElt);
	return element;
};

/**
 * @testable infrastructure
 */
const bookmark = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	const label = primitives.label({
		icon: "bookmark",
		label: display.title,
	});

	element.appendChild(label);
	return element;
};

/**
 * @testable infrastructure
 */
const location = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-col", "gap-1");

	const input = primitives.input({
		label: display.title,
		icon: "location",
		name: schema.id,
		selectIcon: "search",
		type: "text",
		disabled: true,
		placeholder: schema.placeholder,
	});

	element.appendChild(input);
	return element;
};

/**
 * @testable infrastructure
 */
const select = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-col", "gap-1");

	const select = primitives.select({
		label: display.title,
		icon: "select",
		selectIcon: "dropdown",
		name: schema.id,
		disabled: true,
		placeholder: schema.placeholder || "select an option...",
	});

	element.appendChild(select);
	return element;
};

/**
 * @testable infrastructure
 */
const radio = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	const fieldset = element.appendChild(document.createElement("fieldset"));
	fieldset.className = `${STYLES.radio.fieldset.column}`;

	fieldset.appendChild(
		primitives.label({
			icon: "radio",
			tag: "legend",
			label: display.title,
		}),
	);

	if (!schema.options) {
		return element;
	}

	schema.options.forEach((option) => {
		fieldset.appendChild(
			primitives.radio({
				label: option.label,
				value: option.value,
				name: schema.id,
				disabled: true,
				styles: {
					label: `${STYLES.radio.label} first-of-type:pt-1`,
				},
			}),
		);
	});

	return element;
};

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_signature_field_builder_unique_component
 * @features forms signature
 * @dimensions builder-signature-field builder-preview
 */
const signature = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	const label = primitives.label({
		icon: "signature",
		label: display.title,
		tag: "h3",
	});

	element.appendChild(label);
	return element;
};

/**
 * @testable infrastructure
 */
const status = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);

	const label = primitives.label({
		tag: "h3",
		label: display.title,
		icon: "status",
	});

	element.appendChild(label);
	return element;
};

/**
 * @testable infrastructure
 */
const textarea = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-col", "gap-1");

	const textarea = primitives.textarea({
		label: display.title,
		placeholder: schema.placeholder || "",
		icon: "textarea",
		disabled: true,
		rows: 2,
	});

	element.appendChild(textarea);
	return element;
};

/**
 * @testable infrastructure
 */
const table = (schema) => {
	const element = _model(schema);
	const display = _presentation(schema);
	element.classList.add("flex", "flex-col", "gap-1");
	const columns = schema.columns || [];

	const label = primitives.label({
		icon: "table",
		label: display.title,
		tag: "h3",
	});
	element.appendChild(label);

	const badgesContainer = element.appendChild(document.createElement("div"));
	badgesContainer.className = `flex flex-row gap-2 empty:hidden flex-wrap`;

	columns.forEach((column) => {
		badgesContainer.appendChild(
			primitives.badge({
				icon: column.location || column.input || column.type,
				text: column.title,
				kind: "form",
				styles: {
					badge: `${STYLES.badge.builder}`,
					text: "text-base-dark",
				},
			}),
		);
	});

	return element;
};

const ModelElement = {
	checkbox,
	html,
	input,
	link,
	bookmark,
	location,
	radio,
	select,
	signature,
	status,
	textarea,
	table,
};

/**
 * @testable false
 * @covered-by src/script/views/builder/builder.mjs::FormBuilder.createFormElements
 * @covered-by src/script/views/builder/panels/components.mjs::ComponentsPanel.init
 * @covered-by src/script/views/builder/panels/components.mjs::ComponentsPanel._click
 * @covered-by src/script/views/builder/panels/header.mjs::Header.saveForm
 * @reason builder behavior is owned by concrete initialization and panel action methods
 */
class FormBuilder {
	constructor(node) {
		this.elt = node;
		this.elements = new Map();
		this.selectedElement = null;
		this.schemaElt = document.querySelector('input[name="schema"]');
		this.key = node.dataset.key;
		this.offlineIndicator = document.querySelector('[data-role="offline"]');
		this.online = connectivity.online;
		this.hidden = connectivity.hidden;
		this.EntityMenu = new EntityMenu(this);

		this.components = new ComponentsPanel(this);
		this.model = new ModelPanel(this);
		this.settings = new ElementSettings(this);
		this.conditions = new ConditionPanel(this);
		this.header = new Header(this);
		this.formSettings = new FormSettings(this);

		this.click = this._click.bind(this);
	}

	async init() {
		this.createFormElements();

		this.model.init();
		this.settings.init();
		this.formSettings.init();

		const offlineModal = new OfflineModal(this, this.offlineIndicator);
		offlineModal.enable();
		this.offline(!this.online);

		document.addEventListener("click", this.click);
		this.elt._lp_view = this;

		this._initSearch();
		this.elt.setAttribute("initialized", "");
		return this;
	}

	async _initSearch() {
		const search = document.querySelector("[lp-search]");
		if (search) {
			const searchBox = new SearchBox(search);
			await searchBox.init();
		}
	}

	/**
	 * @testable true
	 * @tests tests_js/test_036_form_builder_frontend.py::test_builder_sync_uses_shared_connectivity_without_orphaned_global_state
	 * @pairs forms:builder-lifecycle offline:builder-lifecycle
	 */
	async sync({ hidden = document.hidden } = {}) {
		this.hidden = hidden;
		this.online = connectivity.online;
		this.offline(!this.online);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/builder/builder.mjs::FormBuilder.sync
	 * @reason builder connectivity controls are applied through the shared view lifecycle
	 */
	offline(offline) {
		const search = document.querySelector("[lp-search]");
		if (this.offlineIndicator) {
			this.offlineIndicator.dataset.visible = offline ? "true" : "false";
			this.offlineIndicator.setAttribute(
				"aria-hidden",
				offline ? "false" : "true",
			);
		}
		if (search) search.dataset.visible = offline ? "false" : "true";
		const saveButton = this.header.saveButton;
		if (saveButton) saveButton.dataset.visible = offline ? "false" : "true";
	}

	updateSchema(silent = false) {
		const schemas = Array.from(this.elements.values()).map(
			(element) => element.schema,
		);
		const schemaString = JSON.stringify(schemas);
		if (schemaString !== this.schemaElt.value) {
			this.schemaElt.value = schemaString;
			!silent && this.header.unsaved();
		}
	}

	get schema() {
		return JSON.parse(this.schemaElt.value);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
	 * @features forms
	 * @dimensions page-form task-form builder-defaults
	 */
	async createFormElements() {
		const recentSchema = this.schemaElt.value;
		const schemaJSON = recentSchema ? recentSchema : this.elt.dataset.schema;
		const schema = schemaJSON ? JSON.parse(schemaJSON) : [];

		for (const elt of schema) {
			this.createElement(elt);
		}

		this.updateSchema(true);
	}

	_click(event) {
		const menuTrigger = event.target.closest("[data-role='menu-trigger']");
		const menu = menuTrigger?.closest("[lp-menu]");
		if (menu && this.elt.contains(menu)) {
			event.preventDefault();
			event.stopPropagation();
			this.EntityMenu.toggle(menu);
			return;
		}

		const button = event.target.closest("button");
		const element = event.target.closest(".form-element");
		const preview = event.target.closest("#preview-panel");

		if (element && !preview) {
			this.selectElement(element.id);
		} else if (button?.hasAttribute("lp-help")) {
			this._showHelpModal(button);
		} else if (button?.dataset.role === "form-settings") {
			this.deselectElement();
			this.formSettings.visible = true;
		} else if (button?.id === "preview-toggle") {
			this.header.togglePreviewPanel();
		} else if (button?.dataset.role === "save-form") {
			this.header.saveForm();
		} else if (button?.dataset.action === "copy-form") {
			this.copyForm(button);
		} else if (button?.getAttribute("lp-control") === "delete") {
			this._showDeleteModal(button);
		} else if (event.target?.id === "form-name-display") {
			this.header.editFormName();
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_copy_form_from_builder_title_menu
	 * @pairs forms:builder-copy forms:schema forms:navigation
	 * @pairs entity-menu:builder-copy
	 */
	async copyForm(button) {
		if (!button?.dataset.route || button.disabled) return;

		button.disabled = true;
		const response = await request.post(button.dataset.route, {
			name: this.header.nameDisplay.textContent.trim(),
			schema: this.schema,
		});
		if (response?.ok && response.url) {
			window.location.assign(response.url);
			return;
		}

		button.disabled = false;
		this.header.message(response?.error || "Could not copy this form.");
	}

	async _showDeleteModal(button) {
		const modal = new DeleteModal(this, button);
		await modal.init();
	}

	async _showHelpModal(button) {
		const modal = new HelpModal(this, button);
		await modal.init();
	}

	selectElement(id) {
		this.selectedElement = this.elements.get(id);
		withTransition(() => {
			this.model.selectItem();
			this.settings.selectItem();
		});
	}

	deselectElement() {
		this.model.deselectItem();
		this.settings.deselectItem();
		this.selectedElement = null;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_036_form_builder_frontend.py::test_table_creation_defaults_columns_for_unsaved_preview
	 * @features forms form-table
	 * @dimensions builder-defaults unsaved-preview empty-columns
	 */
	createElement(schema) {
		schema.id = schema.id ?? generateElementId(schema.type);
		if (schema.type === "table" && !Array.isArray(schema.columns)) {
			schema.columns = [];
		}
		const element = ModelElement[schema.type](schema);

		this.elements.set(schema.id, {
			item: element,
			schema: schema,
			settings: this.settings.create(schema),
		});

		return element;
	}

	getEligibleConditionTargets() {
		return Array.from(this.elements.values())
			.filter(
				(element) =>
					["checkbox", "radio", "select"].includes(element.schema.type) &&
					element !== this.selectedElement,
			)
			.map((element) => ({
				label: element.schema.title,
				value: element.schema.id,
				details: {
					icon: element.schema.type,
					kind: "form",
					name: element.schema.title,
				},
			}));
	}

	async showCondition(name, index = -1) {
		if (this.conditions.loading) return;
		this.conditions.loading = true;
		const element = this.selectedElement;

		element.conditions ??= {};
		let condition = element.conditions[name] ?? null;
		if (!condition) {
			condition = await loadCondition(this, name);
			element.conditions[name] = condition;
		}

		if (!element.destroy) {
			element.destroy = () => {
				Object.values(element.conditions).forEach((condition) => {
					condition.destroy();
				});
			};
		}

		condition.index = index;
		await condition.init();

		await withTransition(
			() => {
				this.conditions.open(condition);
			},
			{ label: "builder:show-condition" },
		);
	}

	updateSchemaOrder() {
		const sortedMap = new Map();

		Array.from(this.model.defaults).forEach((element) => {
			sortedMap.set(element.id, this.elements.get(element.id));
		});

		Array.from(this.model.elements).forEach((element) => {
			sortedMap.set(element.id, this.elements.get(element.id));
		});

		this.elements = sortedMap;

		this.updateSchema();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_delete_components
	 * @features forms
	 * @dimensions builder-delete-components
	 */
	removeElement() {
		if (this.selectedElement.destroy) this.selectedElement.destroy();
		this.selectedElement.item.remove();
		this.elements.delete(this.selectedElement.schema.id);

		this.selectedElement = null;
		this.updateSchema();
	}

	destroy() {
		this.components.destroy();
		this.model.destroy();
		this.header.destroy();
		this.formSettings.destroy();
		this.EntityMenu.destroy();

		this.elements.forEach((element) => {
			if (element.destroy) element.destroy();
		});
		this.elements.clear();

		document.removeEventListener("click", this.click);
	}
}

export { CONFIG as C, FormBuilder as F };
