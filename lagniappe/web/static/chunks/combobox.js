/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES, s as setIcon } from './ui-resources.js?v=bcd14aa3';
import { g as generateElementId, c as captureError, Q as QueryLifecycle, d as debounce, e as localStore, E as ENDPOINTS, r as request } from './foundation.js?v=bcd14aa3';
import { p as primitives, f as formatting } from './ui-controls.js?v=bcd14aa3';

/**
 * Custom positioning reference element.
 * @see https://floating-ui.com/docs/virtual-elements
 */

const min = Math.min;
const max = Math.max;
const round = Math.round;
const floor = Math.floor;
const createCoords = v => ({
  x: v,
  y: v
});
const oppositeSideMap = {
  left: 'right',
  right: 'left',
  bottom: 'top',
  top: 'bottom'
};
function clamp(start, value, end) {
  return max(start, min(value, end));
}
function evaluate(value, param) {
  return typeof value === 'function' ? value(param) : value;
}
function getSide(placement) {
  return placement.split('-')[0];
}
function getAlignment(placement) {
  return placement.split('-')[1];
}
function getOppositeAxis(axis) {
  return axis === 'x' ? 'y' : 'x';
}
function getAxisLength(axis) {
  return axis === 'y' ? 'height' : 'width';
}
function getSideAxis(placement) {
  const firstChar = placement[0];
  return firstChar === 't' || firstChar === 'b' ? 'y' : 'x';
}
function getAlignmentAxis(placement) {
  return getOppositeAxis(getSideAxis(placement));
}
function getAlignmentSides(placement, rects, rtl) {
  if (rtl === void 0) {
    rtl = false;
  }
  const alignment = getAlignment(placement);
  const alignmentAxis = getAlignmentAxis(placement);
  const length = getAxisLength(alignmentAxis);
  let mainAlignmentSide = alignmentAxis === 'x' ? alignment === (rtl ? 'end' : 'start') ? 'right' : 'left' : alignment === 'start' ? 'bottom' : 'top';
  if (rects.reference[length] > rects.floating[length]) {
    mainAlignmentSide = getOppositePlacement(mainAlignmentSide);
  }
  return [mainAlignmentSide, getOppositePlacement(mainAlignmentSide)];
}
function getExpandedPlacements(placement) {
  const oppositePlacement = getOppositePlacement(placement);
  return [getOppositeAlignmentPlacement(placement), oppositePlacement, getOppositeAlignmentPlacement(oppositePlacement)];
}
function getOppositeAlignmentPlacement(placement) {
  return placement.includes('start') ? placement.replace('start', 'end') : placement.replace('end', 'start');
}
const lrPlacement = ['left', 'right'];
const rlPlacement = ['right', 'left'];
const tbPlacement = ['top', 'bottom'];
const btPlacement = ['bottom', 'top'];
function getSideList(side, isStart, rtl) {
  switch (side) {
    case 'top':
    case 'bottom':
      if (rtl) return isStart ? rlPlacement : lrPlacement;
      return isStart ? lrPlacement : rlPlacement;
    case 'left':
    case 'right':
      return isStart ? tbPlacement : btPlacement;
    default:
      return [];
  }
}
function getOppositeAxisPlacements(placement, flipAlignment, direction, rtl) {
  const alignment = getAlignment(placement);
  let list = getSideList(getSide(placement), direction === 'start', rtl);
  if (alignment) {
    list = list.map(side => side + "-" + alignment);
    if (flipAlignment) {
      list = list.concat(list.map(getOppositeAlignmentPlacement));
    }
  }
  return list;
}
function getOppositePlacement(placement) {
  const side = getSide(placement);
  return oppositeSideMap[side] + placement.slice(side.length);
}
function expandPaddingObject(padding) {
  var _padding$top, _padding$right, _padding$bottom, _padding$left;
  return {
    top: (_padding$top = padding.top) != null ? _padding$top : 0,
    right: (_padding$right = padding.right) != null ? _padding$right : 0,
    bottom: (_padding$bottom = padding.bottom) != null ? _padding$bottom : 0,
    left: (_padding$left = padding.left) != null ? _padding$left : 0
  };
}
function getPaddingObject(padding) {
  return typeof padding !== 'number' ? expandPaddingObject(padding) : {
    top: padding,
    right: padding,
    bottom: padding,
    left: padding
  };
}
function rectToClientRect(rect) {
  const {
    x,
    y,
    width,
    height
  } = rect;
  return {
    width,
    height,
    top: y,
    left: x,
    right: x + width,
    bottom: y + height,
    x,
    y
  };
}

function computeCoordsFromPlacement(_ref, placement, rtl) {
  let {
    reference,
    floating
  } = _ref;
  const sideAxis = getSideAxis(placement);
  const alignmentAxis = getAlignmentAxis(placement);
  const alignLength = getAxisLength(alignmentAxis);
  const side = getSide(placement);
  const isVertical = sideAxis === 'y';
  const commonX = reference.x + reference.width / 2 - floating.width / 2;
  const commonY = reference.y + reference.height / 2 - floating.height / 2;
  const commonAlign = reference[alignLength] / 2 - floating[alignLength] / 2;
  let coords;
  switch (side) {
    case 'top':
      coords = {
        x: commonX,
        y: reference.y - floating.height
      };
      break;
    case 'bottom':
      coords = {
        x: commonX,
        y: reference.y + reference.height
      };
      break;
    case 'right':
      coords = {
        x: reference.x + reference.width,
        y: commonY
      };
      break;
    case 'left':
      coords = {
        x: reference.x - floating.width,
        y: commonY
      };
      break;
    default:
      coords = {
        x: reference.x,
        y: reference.y
      };
  }
  const alignment = getAlignment(placement);
  if (alignment) {
    coords[alignmentAxis] += commonAlign * (alignment === 'end' ? 1 : -1) * (rtl && isVertical ? -1 : 1);
  }
  return coords;
}

/**
 * Resolves with an object of overflow side offsets that determine how much the
 * element is overflowing a given clipping boundary on each side.
 * - positive = overflowing the boundary by that number of pixels
 * - negative = how many pixels left before it will overflow
 * - 0 = lies flush with the boundary
 * @see https://floating-ui.com/docs/detectOverflow
 */
async function detectOverflow(state, options) {
  var _await$platform$isEle;
  if (options === void 0) {
    options = {};
  }
  const {
    x,
    y,
    platform,
    rects,
    elements,
    strategy
  } = state;
  const {
    boundary = 'clippingAncestors',
    rootBoundary = 'viewport',
    elementContext = 'floating',
    altBoundary = false,
    padding = 0
  } = evaluate(options, state);
  const paddingObject = getPaddingObject(padding);
  const altContext = elementContext === 'floating' ? 'reference' : 'floating';
  const element = elements[altBoundary ? altContext : elementContext];
  const clippingClientRect = rectToClientRect(await platform.getClippingRect({
    element: ((_await$platform$isEle = await (platform.isElement == null ? void 0 : platform.isElement(element))) != null ? _await$platform$isEle : true) ? element : element.contextElement || (await (platform.getDocumentElement == null ? void 0 : platform.getDocumentElement(elements.floating))),
    boundary,
    rootBoundary,
    strategy
  }));
  const rect = elementContext === 'floating' ? {
    x,
    y,
    width: rects.floating.width,
    height: rects.floating.height
  } : rects.reference;
  const offsetParent = await (platform.getOffsetParent == null ? void 0 : platform.getOffsetParent(elements.floating));
  const offsetScale = (await (platform.isElement == null ? void 0 : platform.isElement(offsetParent))) && (await (platform.getScale == null ? void 0 : platform.getScale(offsetParent))) || {
    x: 1,
    y: 1
  };
  const elementClientRect = rectToClientRect(platform.convertOffsetParentRelativeRectToViewportRelativeRect ? await platform.convertOffsetParentRelativeRectToViewportRelativeRect({
    elements,
    rect,
    offsetParent,
    strategy
  }) : rect);
  return {
    top: (clippingClientRect.top - elementClientRect.top + paddingObject.top) / offsetScale.y,
    bottom: (elementClientRect.bottom - clippingClientRect.bottom + paddingObject.bottom) / offsetScale.y,
    left: (clippingClientRect.left - elementClientRect.left + paddingObject.left) / offsetScale.x,
    right: (elementClientRect.right - clippingClientRect.right + paddingObject.right) / offsetScale.x
  };
}

// Maximum number of resets that can occur before bailing to avoid infinite reset loops.
const MAX_RESET_COUNT = 50;

/**
 * Computes the `x` and `y` coordinates that will place the floating element
 * next to a given reference element.
 *
 * This export does not have any `platform` interface logic. You will need to
 * write one for the platform you are using Floating UI with.
 */
const computePosition$1 = async (reference, floating, config) => {
  const {
    placement = 'bottom',
    strategy = 'absolute',
    middleware = [],
    platform
  } = config;
  const platformWithDetectOverflow = platform.detectOverflow ? platform : {
    ...platform,
    detectOverflow
  };
  const rtl = await (platform.isRTL == null ? void 0 : platform.isRTL(floating));
  let rects = await platform.getElementRects({
    reference,
    floating,
    strategy
  });
  let {
    x,
    y
  } = computeCoordsFromPlacement(rects, placement, rtl);
  let statefulPlacement = placement;
  let resetCount = 0;
  const middlewareData = {};
  for (let i = 0; i < middleware.length; i++) {
    const currentMiddleware = middleware[i];
    if (!currentMiddleware) {
      continue;
    }
    const {
      name,
      fn
    } = currentMiddleware;
    const {
      x: nextX,
      y: nextY,
      data,
      reset
    } = await fn({
      x,
      y,
      initialPlacement: placement,
      placement: statefulPlacement,
      strategy,
      middlewareData,
      rects,
      platform: platformWithDetectOverflow,
      elements: {
        reference,
        floating
      }
    });
    x = nextX != null ? nextX : x;
    y = nextY != null ? nextY : y;
    middlewareData[name] = {
      ...middlewareData[name],
      ...data
    };
    if (reset && resetCount < MAX_RESET_COUNT) {
      resetCount++;
      if (typeof reset === 'object') {
        if (reset.placement) {
          statefulPlacement = reset.placement;
        }
        if (reset.rects) {
          rects = reset.rects === true ? await platform.getElementRects({
            reference,
            floating,
            strategy
          }) : reset.rects;
        }
        ({
          x,
          y
        } = computeCoordsFromPlacement(rects, statefulPlacement, rtl));
      }
      i = -1;
    }
  }
  return {
    x,
    y,
    placement: statefulPlacement,
    strategy,
    middlewareData
  };
};

/**
 * Optimizes the visibility of the floating element by flipping the `placement`
 * in order to keep it in view when the preferred placement(s) will overflow the
 * clipping boundary. Alternative to `autoPlacement`.
 * @see https://floating-ui.com/docs/flip
 */
const flip$1 = function (options) {
  if (options === void 0) {
    options = {};
  }
  return {
    name: 'flip',
    options,
    async fn(state) {
      var _middlewareData$arrow, _middlewareData$flip;
      const {
        placement,
        middlewareData,
        rects,
        initialPlacement,
        platform,
        elements
      } = state;
      const {
        mainAxis: checkMainAxis = true,
        crossAxis: checkCrossAxis = true,
        fallbackPlacements: specifiedFallbackPlacements,
        fallbackStrategy = 'bestFit',
        fallbackAxisSideDirection = 'none',
        flipAlignment = true,
        ...detectOverflowOptions
      } = evaluate(options, state);

      // If a reset by the arrow was caused due to an alignment offset being
      // added, we should skip any logic now since `flip()` has already done its
      // work.
      // https://github.com/floating-ui/floating-ui/issues/2549#issuecomment-1719601643
      if ((_middlewareData$arrow = middlewareData.arrow) != null && _middlewareData$arrow.alignmentOffset) {
        return {};
      }
      const side = getSide(placement);
      const initialSideAxis = getSideAxis(initialPlacement);
      const isBasePlacement = getSide(initialPlacement) === initialPlacement;
      const rtl = await (platform.isRTL == null ? void 0 : platform.isRTL(elements.floating));
      const fallbackPlacements = specifiedFallbackPlacements || (isBasePlacement || !flipAlignment ? [getOppositePlacement(initialPlacement)] : getExpandedPlacements(initialPlacement));
      const hasFallbackAxisSideDirection = fallbackAxisSideDirection !== 'none';
      if (!specifiedFallbackPlacements && hasFallbackAxisSideDirection) {
        fallbackPlacements.push(...getOppositeAxisPlacements(initialPlacement, flipAlignment, fallbackAxisSideDirection, rtl));
      }
      const placements = [initialPlacement, ...fallbackPlacements];
      const overflow = await platform.detectOverflow(state, detectOverflowOptions);
      const overflows = [];
      let overflowsData = ((_middlewareData$flip = middlewareData.flip) == null ? void 0 : _middlewareData$flip.overflows) || [];
      if (checkMainAxis) {
        overflows.push(overflow[side]);
      }
      if (checkCrossAxis) {
        const sides = getAlignmentSides(placement, rects, rtl);
        overflows.push(overflow[sides[0]], overflow[sides[1]]);
      }
      overflowsData = [...overflowsData, {
        placement,
        overflows
      }];

      // One or more sides is overflowing.
      if (!overflows.every(side => side <= 0)) {
        var _middlewareData$flip2, _overflowsData$filter;
        const nextIndex = (((_middlewareData$flip2 = middlewareData.flip) == null ? void 0 : _middlewareData$flip2.index) || 0) + 1;
        const nextPlacement = placements[nextIndex];
        if (nextPlacement) {
          const ignoreCrossAxisOverflow = checkCrossAxis === 'alignment' ? initialSideAxis !== getSideAxis(nextPlacement) : false;
          if (!ignoreCrossAxisOverflow ||
          // We leave the current main axis only if every placement on that axis
          // overflows the main axis.
          overflowsData.every(d => getSideAxis(d.placement) === initialSideAxis ? d.overflows[0] > 0 : true)) {
            // Try next placement and re-run the lifecycle.
            return {
              data: {
                index: nextIndex,
                overflows: overflowsData
              },
              reset: {
                placement: nextPlacement
              }
            };
          }
        }

        // First, find the candidates that fit on the mainAxis side of overflow,
        // then find the placement that fits the best on the main crossAxis side.
        let resetPlacement = (_overflowsData$filter = overflowsData.filter(d => d.overflows[0] <= 0).sort((a, b) => a.overflows[1] - b.overflows[1])[0]) == null ? void 0 : _overflowsData$filter.placement;

        // Otherwise fallback.
        if (!resetPlacement) {
          switch (fallbackStrategy) {
            case 'bestFit':
              {
                var _overflowsData$filter2;
                const placement = (_overflowsData$filter2 = overflowsData.filter(d => {
                  if (hasFallbackAxisSideDirection) {
                    const currentSideAxis = getSideAxis(d.placement);
                    return currentSideAxis === initialSideAxis ||
                    // Create a bias to the `y` side axis due to horizontal
                    // reading directions favoring greater width.
                    currentSideAxis === 'y';
                  }
                  return true;
                }).map(d => [d.placement, d.overflows.filter(overflow => overflow > 0).reduce((acc, overflow) => acc + overflow, 0)]).sort((a, b) => a[1] - b[1])[0]) == null ? void 0 : _overflowsData$filter2[0];
                if (placement) {
                  resetPlacement = placement;
                }
                break;
              }
            case 'initialPlacement':
              resetPlacement = initialPlacement;
              break;
          }
        }
        if (placement !== resetPlacement) {
          return {
            reset: {
              placement: resetPlacement
            }
          };
        }
      }
      return {};
    }
  };
};

const originSides = /*#__PURE__*/new Set(['left', 'top']);

// For type backwards-compatibility, the `OffsetOptions` type was also
// Derivable.

async function convertValueToCoords(state, options) {
  const {
    placement,
    platform,
    elements
  } = state;
  const rtl = await (platform.isRTL == null ? void 0 : platform.isRTL(elements.floating));
  const side = getSide(placement);
  const alignment = getAlignment(placement);
  const isVertical = getSideAxis(placement) === 'y';
  const mainAxisMulti = originSides.has(side) ? -1 : 1;
  const crossAxisMulti = rtl && isVertical ? -1 : 1;
  const rawValue = evaluate(options, state);

  // eslint-disable-next-line prefer-const
  let {
    mainAxis,
    crossAxis,
    alignmentAxis
  } = typeof rawValue === 'number' ? {
    mainAxis: rawValue,
    crossAxis: 0,
    alignmentAxis: null
  } : {
    mainAxis: rawValue.mainAxis || 0,
    crossAxis: rawValue.crossAxis || 0,
    alignmentAxis: rawValue.alignmentAxis
  };
  if (alignment && typeof alignmentAxis === 'number') {
    crossAxis = alignment === 'end' ? alignmentAxis * -1 : alignmentAxis;
  }
  return isVertical ? {
    x: crossAxis * crossAxisMulti,
    y: mainAxis * mainAxisMulti
  } : {
    x: mainAxis * mainAxisMulti,
    y: crossAxis * crossAxisMulti
  };
}

/**
 * Modifies the placement by translating the floating element along the
 * specified axes.
 * A number (shorthand for `mainAxis` or distance), or an axes configuration
 * object may be passed.
 * @see https://floating-ui.com/docs/offset
 */
const offset$1 = function (options) {
  if (options === void 0) {
    options = 0;
  }
  return {
    name: 'offset',
    options,
    async fn(state) {
      var _middlewareData$offse, _middlewareData$arrow;
      const {
        x,
        y,
        placement,
        middlewareData
      } = state;
      const diffCoords = await convertValueToCoords(state, options);

      // If the placement is the same and the arrow caused an alignment offset
      // then we don't need to change the positioning coordinates.
      if (placement === ((_middlewareData$offse = middlewareData.offset) == null ? void 0 : _middlewareData$offse.placement) && (_middlewareData$arrow = middlewareData.arrow) != null && _middlewareData$arrow.alignmentOffset) {
        return {};
      }
      return {
        x: x + diffCoords.x,
        y: y + diffCoords.y,
        data: {
          ...diffCoords,
          placement
        }
      };
    }
  };
};

/**
 * Optimizes the visibility of the floating element by shifting it in order to
 * keep it in view when it will overflow the clipping boundary.
 * @see https://floating-ui.com/docs/shift
 */
const shift$1 = function (options) {
  if (options === void 0) {
    options = {};
  }
  return {
    name: 'shift',
    options,
    async fn(state) {
      const {
        x,
        y,
        placement,
        platform
      } = state;
      const {
        mainAxis: checkMainAxis = true,
        crossAxis: checkCrossAxis = false,
        limiter = {
          fn: _ref => {
            let {
              x,
              y
            } = _ref;
            return {
              x,
              y
            };
          }
        },
        ...detectOverflowOptions
      } = evaluate(options, state);
      const coords = {
        x,
        y
      };
      const overflow = await platform.detectOverflow(state, detectOverflowOptions);
      const crossAxis = getSideAxis(placement);
      const mainAxis = getOppositeAxis(crossAxis);
      let mainAxisCoord = coords[mainAxis];
      let crossAxisCoord = coords[crossAxis];
      const clampCoord = (axis, coord) => clamp(coord + overflow[axis === 'y' ? 'top' : 'left'], coord, coord - overflow[axis === 'y' ? 'bottom' : 'right']);
      if (checkMainAxis) {
        mainAxisCoord = clampCoord(mainAxis, mainAxisCoord);
      }
      if (checkCrossAxis) {
        crossAxisCoord = clampCoord(crossAxis, crossAxisCoord);
      }
      const limitedCoords = limiter.fn({
        ...state,
        [mainAxis]: mainAxisCoord,
        [crossAxis]: crossAxisCoord
      });
      return {
        ...limitedCoords,
        data: {
          x: limitedCoords.x - x,
          y: limitedCoords.y - y,
          enabled: {
            [mainAxis]: checkMainAxis,
            [crossAxis]: checkCrossAxis
          }
        }
      };
    }
  };
};

function hasWindow() {
  return typeof window !== 'undefined';
}
function getNodeName(node) {
  if (isNode(node)) {
    return (node.nodeName || '').toLowerCase();
  }
  // Mocked nodes in testing environments may not be instances of Node. By
  // returning `#document` an infinite loop won't occur.
  // https://github.com/floating-ui/floating-ui/issues/2317
  return '#document';
}
function getWindow(node) {
  var _node$ownerDocument;
  return (node == null || (_node$ownerDocument = node.ownerDocument) == null ? void 0 : _node$ownerDocument.defaultView) || window;
}
function getDocumentElement(node) {
  var _ref;
  return (_ref = (isNode(node) ? node.ownerDocument : node.document) || window.document) == null ? void 0 : _ref.documentElement;
}
function isNode(value) {
  if (!hasWindow()) {
    return false;
  }
  return value instanceof Node || value instanceof getWindow(value).Node;
}
function isElement(value) {
  if (!hasWindow()) {
    return false;
  }
  return value instanceof Element || value instanceof getWindow(value).Element;
}
function isHTMLElement(value) {
  if (!hasWindow()) {
    return false;
  }
  return value instanceof HTMLElement || value instanceof getWindow(value).HTMLElement;
}
function isShadowRoot(value) {
  if (!hasWindow() || typeof ShadowRoot === 'undefined') {
    return false;
  }
  return value instanceof ShadowRoot || value instanceof getWindow(value).ShadowRoot;
}
function isOverflowElement(element) {
  const {
    overflow,
    overflowX,
    overflowY,
    display
  } = getComputedStyle$1(element);
  return /auto|scroll|overlay|hidden|clip/.test(overflow + overflowY + overflowX) && display !== 'inline' && display !== 'contents';
}
function isTableElement(element) {
  return /^(table|td|th)$/.test(getNodeName(element));
}
function isTopLayer(element) {
  try {
    if (element.matches(':popover-open')) {
      return true;
    }
  } catch (_e) {
    // no-op
  }
  try {
    return element.matches(':modal');
  } catch (_e) {
    return false;
  }
}
const willChangeRe = /transform|translate|scale|rotate|perspective|filter/;
const containRe = /paint|layout|strict|content/;
const isNotNone = value => !!value && value !== 'none';
let isWebKitValue;
function isContainingBlock(elementOrCss) {
  const css = isElement(elementOrCss) ? getComputedStyle$1(elementOrCss) : elementOrCss;

  // https://developer.mozilla.org/en-US/docs/Web/CSS/Containing_block#identifying_the_containing_block
  // https://drafts.csswg.org/css-transforms-2/#individual-transforms
  return isNotNone(css.transform) || isNotNone(css.translate) || isNotNone(css.scale) || isNotNone(css.rotate) || isNotNone(css.perspective) || !isWebKit() && (isNotNone(css.backdropFilter) || isNotNone(css.filter)) || willChangeRe.test(css.willChange || '') || containRe.test(css.contain || '');
}
function getContainingBlock(element) {
  let currentNode = getParentNode(element);
  while (isHTMLElement(currentNode) && !isLastTraversableNode(currentNode)) {
    if (isContainingBlock(currentNode)) {
      return currentNode;
    } else if (isTopLayer(currentNode)) {
      return null;
    }
    currentNode = getParentNode(currentNode);
  }
  return null;
}
function isWebKit() {
  if (isWebKitValue == null) {
    isWebKitValue = typeof CSS !== 'undefined' && CSS.supports && CSS.supports('-webkit-backdrop-filter', 'none');
  }
  return isWebKitValue;
}
function isLastTraversableNode(node) {
  return /^(html|body|#document)$/.test(getNodeName(node));
}
function getComputedStyle$1(element) {
  return getWindow(element).getComputedStyle(element);
}
function getNodeScroll(element) {
  if (isElement(element)) {
    return {
      scrollLeft: element.scrollLeft,
      scrollTop: element.scrollTop
    };
  }
  return {
    scrollLeft: element.scrollX,
    scrollTop: element.scrollY
  };
}
function getParentNode(node) {
  if (getNodeName(node) === 'html') {
    return node;
  }
  const result =
  // Step into the shadow DOM of the parent of a slotted node.
  node.assignedSlot ||
  // DOM Element detected.
  node.parentNode ||
  // ShadowRoot detected.
  isShadowRoot(node) && node.host ||
  // Fallback.
  getDocumentElement(node);
  return isShadowRoot(result) ? result.host : result;
}
function getNearestOverflowAncestor(node) {
  const parentNode = getParentNode(node);
  if (isLastTraversableNode(parentNode)) {
    return (node.ownerDocument || node).body;
  }
  if (isHTMLElement(parentNode) && isOverflowElement(parentNode)) {
    return parentNode;
  }
  return getNearestOverflowAncestor(parentNode);
}
function getOverflowAncestors(node, list, traverseIframes) {
  var _node$ownerDocument2;
  if (list === void 0) {
    list = [];
  }
  if (traverseIframes === void 0) {
    traverseIframes = true;
  }
  const scrollableAncestor = getNearestOverflowAncestor(node);
  const isBody = scrollableAncestor === ((_node$ownerDocument2 = node.ownerDocument) == null ? void 0 : _node$ownerDocument2.body);
  const win = getWindow(scrollableAncestor);
  if (isBody) {
    const frameElement = getFrameElement(win);
    return list.concat(win, win.visualViewport || [], isOverflowElement(scrollableAncestor) ? scrollableAncestor : [], frameElement && traverseIframes ? getOverflowAncestors(frameElement) : []);
  } else {
    return list.concat(scrollableAncestor, getOverflowAncestors(scrollableAncestor, [], traverseIframes));
  }
}
function getFrameElement(win) {
  return win.parent && Object.getPrototypeOf(win.parent) ? win.frameElement : null;
}

function getCssDimensions(element) {
  const css = getComputedStyle$1(element);
  // In testing environments, the `width` and `height` properties are empty
  // strings for SVG elements, returning NaN. Fallback to `0` in this case.
  let width = parseFloat(css.width) || 0;
  let height = parseFloat(css.height) || 0;
  const hasOffset = isHTMLElement(element);
  const offsetWidth = hasOffset ? element.offsetWidth : width;
  const offsetHeight = hasOffset ? element.offsetHeight : height;
  const shouldFallback = round(width) !== offsetWidth || round(height) !== offsetHeight;
  if (shouldFallback) {
    width = offsetWidth;
    height = offsetHeight;
  }
  return {
    width,
    height,
    $: shouldFallback
  };
}

function unwrapElement(element) {
  return !isElement(element) ? element.contextElement : element;
}

function getScale(element) {
  const domElement = unwrapElement(element);
  if (!isHTMLElement(domElement)) {
    return createCoords(1);
  }
  const rect = domElement.getBoundingClientRect();
  const {
    width,
    height,
    $
  } = getCssDimensions(domElement);
  let x = ($ ? round(rect.width) : rect.width) / width;
  let y = ($ ? round(rect.height) : rect.height) / height;

  // 0, NaN, or Infinity should always fallback to 1.

  if (!x || !Number.isFinite(x)) {
    x = 1;
  }
  if (!y || !Number.isFinite(y)) {
    y = 1;
  }
  return {
    x,
    y
  };
}

const noOffsets = /*#__PURE__*/createCoords(0);
function getVisualOffsets(element) {
  const win = getWindow(element);
  if (!isWebKit() || !win.visualViewport) {
    return noOffsets;
  }
  return {
    x: win.visualViewport.offsetLeft,
    y: win.visualViewport.offsetTop
  };
}
function shouldAddVisualOffsets(element, isFixed, floatingOffsetParent) {
  if (isFixed === void 0) {
    isFixed = false;
  }
  return !!floatingOffsetParent && isFixed && floatingOffsetParent === getWindow(element);
}

function getBoundingClientRect(element, includeScale, isFixedStrategy, offsetParent) {
  if (includeScale === void 0) {
    includeScale = false;
  }
  if (isFixedStrategy === void 0) {
    isFixedStrategy = false;
  }
  const clientRect = element.getBoundingClientRect();
  const domElement = unwrapElement(element);
  let scale = createCoords(1);
  if (includeScale) {
    if (offsetParent) {
      if (isElement(offsetParent)) {
        scale = getScale(offsetParent);
      }
    } else {
      scale = getScale(element);
    }
  }
  const visualOffsets = shouldAddVisualOffsets(domElement, isFixedStrategy, offsetParent) ? getVisualOffsets(domElement) : createCoords(0);
  let x = (clientRect.left + visualOffsets.x) / scale.x;
  let y = (clientRect.top + visualOffsets.y) / scale.y;
  let width = clientRect.width / scale.x;
  let height = clientRect.height / scale.y;
  if (domElement && offsetParent) {
    const win = getWindow(domElement);
    const offsetWin = isElement(offsetParent) ? getWindow(offsetParent) : offsetParent;
    let currentWin = win;
    let currentIFrame = getFrameElement(currentWin);
    while (currentIFrame && offsetWin !== currentWin) {
      const iframeScale = getScale(currentIFrame);
      const iframeRect = currentIFrame.getBoundingClientRect();
      const css = getComputedStyle$1(currentIFrame);
      const left = iframeRect.left + (currentIFrame.clientLeft + parseFloat(css.paddingLeft)) * iframeScale.x;
      const top = iframeRect.top + (currentIFrame.clientTop + parseFloat(css.paddingTop)) * iframeScale.y;
      x *= iframeScale.x;
      y *= iframeScale.y;
      width *= iframeScale.x;
      height *= iframeScale.y;
      x += left;
      y += top;
      currentWin = getWindow(currentIFrame);
      currentIFrame = getFrameElement(currentWin);
    }
  }
  return rectToClientRect({
    width,
    height,
    x,
    y
  });
}

// If <html> has a CSS width greater than the viewport, then this will be
// incorrect for RTL.
function getWindowScrollBarX(element, rect) {
  const leftScroll = getNodeScroll(element).scrollLeft;
  if (!rect) {
    return getBoundingClientRect(getDocumentElement(element)).left + leftScroll;
  }
  return rect.left + leftScroll;
}

function getHTMLOffset(documentElement, scroll) {
  const htmlRect = documentElement.getBoundingClientRect();
  const x = htmlRect.left + scroll.scrollLeft - getWindowScrollBarX(documentElement, htmlRect);
  const y = htmlRect.top + scroll.scrollTop;
  return {
    x,
    y
  };
}

function convertOffsetParentRelativeRectToViewportRelativeRect(_ref) {
  let {
    elements,
    rect,
    offsetParent,
    strategy
  } = _ref;
  const isFixed = strategy === 'fixed';
  const documentElement = getDocumentElement(offsetParent);
  const topLayer = elements ? isTopLayer(elements.floating) : false;
  if (offsetParent === documentElement || topLayer && isFixed) {
    return rect;
  }
  let scroll = {
    scrollLeft: 0,
    scrollTop: 0
  };
  let scale = createCoords(1);
  const offsets = createCoords(0);
  const isOffsetParentAnElement = isHTMLElement(offsetParent);
  if (isOffsetParentAnElement || !isFixed) {
    if (getNodeName(offsetParent) !== 'body' || isOverflowElement(documentElement)) {
      scroll = getNodeScroll(offsetParent);
    }
    if (isOffsetParentAnElement) {
      const offsetRect = getBoundingClientRect(offsetParent);
      scale = getScale(offsetParent);
      offsets.x = offsetRect.x + offsetParent.clientLeft;
      offsets.y = offsetRect.y + offsetParent.clientTop;
    }
  }
  const htmlOffset = documentElement && !isOffsetParentAnElement && !isFixed ? getHTMLOffset(documentElement, scroll) : createCoords(0);
  return {
    width: rect.width * scale.x,
    height: rect.height * scale.y,
    x: rect.x * scale.x - scroll.scrollLeft * scale.x + offsets.x + htmlOffset.x,
    y: rect.y * scale.y - scroll.scrollTop * scale.y + offsets.y + htmlOffset.y
  };
}

function getClientRects(element) {
  return element.getClientRects ? Array.from(element.getClientRects()) : [];
}

// Gets the entire size of the scrollable document area, even extending outside
// of the `<html>` and `<body>` rect bounds if horizontally scrollable.
function getDocumentRect(html) {
  const scroll = getNodeScroll(html);
  const body = html.ownerDocument.body;
  const width = max(html.scrollWidth, html.clientWidth, body.scrollWidth, body.clientWidth);
  const height = max(html.scrollHeight, html.clientHeight, body.scrollHeight, body.clientHeight);
  let x = -scroll.scrollLeft + getWindowScrollBarX(html);
  const y = -scroll.scrollTop;
  if (getComputedStyle$1(body).direction === 'rtl') {
    x += max(html.clientWidth, body.clientWidth) - width;
  }
  return {
    width,
    height,
    x,
    y
  };
}

// Safety check: ensure the scrollbar space is reasonable in case this
// calculation is affected by unusual styles.
// Most scrollbars leave 15-18px of space.
const SCROLLBAR_MAX = 25;
function getViewportRect(element, strategy, rootBoundary) {
  if (rootBoundary === void 0) {
    rootBoundary = 'viewport';
  }
  const isLayoutViewport = rootBoundary === 'layoutViewport';
  const win = getWindow(element);
  const html = getDocumentElement(element);
  const visualViewport = win.visualViewport;
  let width = html.clientWidth;
  let height = html.clientHeight;
  let x = 0;
  let y = 0;
  if (visualViewport) {
    // Client coordinates are relative to the layout viewport, except in
    // WebKit with an `absolute` strategy, where they are relative to the
    // visual viewport.
    const layoutRelativeClientCoords = !isWebKit() || strategy === 'fixed';
    if (isLayoutViewport) {
      if (!layoutRelativeClientCoords) {
        x = -visualViewport.offsetLeft;
        y = -visualViewport.offsetTop;
      }
    } else {
      width = visualViewport.width;
      height = visualViewport.height;
      if (layoutRelativeClientCoords) {
        x = visualViewport.offsetLeft;
        y = visualViewport.offsetTop;
      }
    }
  }
  const windowScrollbarX = getWindowScrollBarX(html);
  // `scrollbar-gutter: stable` on the <html> reserves gutter space that shrinks
  // the visual width but isn't reflected in `html.clientWidth`, so subtract it.
  // Only the inline-end (right) gutter can hold the scrollbar; `both-edges` also
  // reserves an empty inline-start gutter that clips nothing, so exclude just
  // the one scrollbar-side gutter — halve the measured (two-gutter) total. A
  // left-side scrollbar (`windowScrollbarX > 0`) is already handled by
  // `getHTMLOffset`/`visualViewport.width`; skip it here.
  if (windowScrollbarX <= 0) {
    const doc = html.ownerDocument;
    const body = doc.body;
    const bodyStyles = getComputedStyle(body);
    const bodyMarginInline = doc.compatMode === 'CSS1Compat' ? parseFloat(bodyStyles.marginLeft) + parseFloat(bodyStyles.marginRight) || 0 : 0;
    const reservedWidth = Math.abs(html.clientWidth - body.clientWidth - bodyMarginInline);
    const gutter = getComputedStyle(html).scrollbarGutter === 'stable both-edges' ? reservedWidth / 2 : reservedWidth;
    if (gutter <= SCROLLBAR_MAX) {
      width -= gutter;
    }
  }
  return {
    width,
    height,
    x,
    y
  };
}

// Returns the inner client rect, subtracting scrollbars if present.
function getInnerBoundingClientRect(element, strategy) {
  const clientRect = getBoundingClientRect(element, true, strategy === 'fixed');
  const top = clientRect.top + element.clientTop;
  const left = clientRect.left + element.clientLeft;
  const scale = getScale(element);
  const width = element.clientWidth * scale.x;
  const height = element.clientHeight * scale.y;
  const x = left * scale.x;
  const y = top * scale.y;
  return {
    width,
    height,
    x,
    y
  };
}
function getClientRectFromClippingAncestor(element, clippingAncestor, strategy) {
  let rect;
  if (clippingAncestor === 'viewport' || clippingAncestor === 'layoutViewport') {
    rect = getViewportRect(element, strategy, clippingAncestor);
  } else if (clippingAncestor === 'document') {
    rect = getDocumentRect(getDocumentElement(element));
  } else if (isElement(clippingAncestor)) {
    rect = getInnerBoundingClientRect(clippingAncestor, strategy);
  } else {
    const visualOffsets = getVisualOffsets(element);
    rect = {
      x: clippingAncestor.x - visualOffsets.x,
      y: clippingAncestor.y - visualOffsets.y,
      width: clippingAncestor.width,
      height: clippingAncestor.height
    };
  }
  return rectToClientRect(rect);
}

// A "clipping ancestor" is an `overflow` element with the characteristic of
// clipping (or hiding) child elements. This returns all clipping ancestors
// of the given element up the tree.
function getClippingElementAncestors(element, cache) {
  const cachedResult = cache.get(element);
  if (cachedResult) {
    return cachedResult;
  }
  let result = getOverflowAncestors(element, [], false).filter(el => isElement(el) && getNodeName(el) !== 'body');
  let lastKeptComputedStyle = null;
  const elementIsFixed = getComputedStyle$1(element).position === 'fixed';
  let currentNode = elementIsFixed ? getParentNode(element) : element;

  // https://developer.mozilla.org/en-US/docs/Web/CSS/Containing_block#identifying_the_containing_block
  while (isElement(currentNode) && !isLastTraversableNode(currentNode)) {
    const computedStyle = getComputedStyle$1(currentNode);
    const currentNodeIsContaining = isContainingBlock(currentNode);
    // Position of the containing block chain below the current node. A fixed
    // element whose containing block hasn't been found yet is a fixed chain.
    const lastPosition = lastKeptComputedStyle ? lastKeptComputedStyle.position : elementIsFixed ? 'fixed' : '';

    // A non-containing ancestor does not clip the element when the chain
    // below it escapes it: a fixed chain escapes all ancestors up to the
    // next containing block, an absolute chain escapes static ancestors.
    const shouldDropCurrentNode = !currentNodeIsContaining && (lastPosition === 'fixed' || lastPosition === 'absolute' && computedStyle.position === 'static');
    if (shouldDropCurrentNode) {
      // Drop non-containing blocks.
      result = result.filter(ancestor => ancestor !== currentNode);
    } else {
      // The kept node carries the chain position for the next iteration.
      lastKeptComputedStyle = computedStyle;
    }
    currentNode = getParentNode(currentNode);
  }
  cache.set(element, result);
  return result;
}

// Gets the maximum area that the element is visible in due to any number of
// clipping ancestors.
function getClippingRect(_ref) {
  let {
    element,
    boundary,
    rootBoundary,
    strategy
  } = _ref;
  const elementClippingAncestors = boundary === 'clippingAncestors' ? isTopLayer(element) ? [] : getClippingElementAncestors(element, this._c) : [].concat(boundary);
  const clippingAncestors = [...elementClippingAncestors, rootBoundary];
  const firstRect = getClientRectFromClippingAncestor(element, clippingAncestors[0], strategy);
  let top = firstRect.top;
  let right = firstRect.right;
  let bottom = firstRect.bottom;
  let left = firstRect.left;
  for (let i = 1; i < clippingAncestors.length; i++) {
    const rect = getClientRectFromClippingAncestor(element, clippingAncestors[i], strategy);
    top = max(rect.top, top);
    right = min(rect.right, right);
    bottom = min(rect.bottom, bottom);
    left = max(rect.left, left);
  }
  return {
    width: right - left,
    height: bottom - top,
    x: left,
    y: top
  };
}

function getDimensions(element) {
  const {
    width,
    height
  } = getCssDimensions(element);
  return {
    width,
    height
  };
}

function getRectRelativeToOffsetParent(element, offsetParent, strategy) {
  const isOffsetParentAnElement = isHTMLElement(offsetParent);
  const documentElement = getDocumentElement(offsetParent);
  const isFixed = strategy === 'fixed';
  const rect = getBoundingClientRect(element, true, isFixed, offsetParent);
  let scroll = {
    scrollLeft: 0,
    scrollTop: 0
  };
  const offsets = createCoords(0);
  if (isOffsetParentAnElement || !isFixed) {
    if (getNodeName(offsetParent) !== 'body' || isOverflowElement(documentElement)) {
      scroll = getNodeScroll(offsetParent);
    }
    if (isOffsetParentAnElement) {
      const offsetRect = getBoundingClientRect(offsetParent, true, isFixed, offsetParent);
      offsets.x = offsetRect.x + offsetParent.clientLeft;
      offsets.y = offsetRect.y + offsetParent.clientTop;
    }
  }

  // If the <body> scrollbar appears on the left (e.g. RTL systems). Use
  // Firefox with layout.scrollbar.side = 3 in about:config to test this.
  if (!isOffsetParentAnElement && documentElement) {
    offsets.x = getWindowScrollBarX(documentElement);
  }
  const htmlOffset = documentElement && !isOffsetParentAnElement && !isFixed ? getHTMLOffset(documentElement, scroll) : createCoords(0);
  const x = rect.left + scroll.scrollLeft - offsets.x - htmlOffset.x;
  const y = rect.top + scroll.scrollTop - offsets.y - htmlOffset.y;
  return {
    x,
    y,
    width: rect.width,
    height: rect.height
  };
}

function isStaticPositioned(element) {
  return getComputedStyle$1(element).position === 'static';
}

function getTrueOffsetParent(element, polyfill) {
  if (!isHTMLElement(element) || getComputedStyle$1(element).position === 'fixed') {
    return null;
  }
  if (polyfill) {
    return polyfill(element);
  }
  let rawOffsetParent = element.offsetParent;

  // Firefox returns the <html> element as the offsetParent if it's non-static,
  // while Chrome and Safari return the <body> element. The <body> element must
  // be used to perform the correct calculations even if the <html> element is
  // non-static.
  if (getDocumentElement(element) === rawOffsetParent) {
    rawOffsetParent = rawOffsetParent.ownerDocument.body;
  }
  return rawOffsetParent;
}

// Gets the closest ancestor positioned element. Handles some edge cases,
// such as table ancestors and cross browser bugs.
function getOffsetParent(element, polyfill) {
  const win = getWindow(element);
  if (isTopLayer(element)) {
    return win;
  }
  if (!isHTMLElement(element)) {
    let svgOffsetParent = getParentNode(element);
    while (svgOffsetParent && !isLastTraversableNode(svgOffsetParent)) {
      if (isElement(svgOffsetParent) && !isStaticPositioned(svgOffsetParent)) {
        return svgOffsetParent;
      }
      svgOffsetParent = getParentNode(svgOffsetParent);
    }
    return win;
  }
  let offsetParent = getTrueOffsetParent(element, polyfill);
  while (offsetParent && isTableElement(offsetParent) && isStaticPositioned(offsetParent)) {
    offsetParent = getTrueOffsetParent(offsetParent, polyfill);
  }
  if (offsetParent && isLastTraversableNode(offsetParent) && isStaticPositioned(offsetParent) && !isContainingBlock(offsetParent)) {
    return win;
  }
  return offsetParent || getContainingBlock(element) || win;
}

const getElementRects = async function (data) {
  const getOffsetParentFn = this.getOffsetParent || getOffsetParent;
  const getDimensionsFn = this.getDimensions;
  const floatingDimensions = await getDimensionsFn(data.floating);
  return {
    reference: getRectRelativeToOffsetParent(data.reference, await getOffsetParentFn(data.floating), data.strategy),
    floating: {
      x: 0,
      y: 0,
      width: floatingDimensions.width,
      height: floatingDimensions.height
    }
  };
};

function isRTL(element) {
  return getComputedStyle$1(element).direction === 'rtl';
}

const platform = {
  convertOffsetParentRelativeRectToViewportRelativeRect,
  getDocumentElement,
  getClippingRect,
  getOffsetParent,
  getElementRects,
  getClientRects,
  getDimensions,
  getScale,
  isElement,
  isRTL
};

function rectsAreEqual(a, b) {
  return a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height;
}

// https://samthor.au/2021/observing-dom/
function observeMove(element, onMove, ancestorResize) {
  let io = null;
  let timeoutId;
  const root = getDocumentElement(element);
  function cleanup() {
    var _io;
    clearTimeout(timeoutId);
    (_io = io) == null || _io.disconnect();
    io = null;
  }
  function refresh(skip, threshold) {
    if (skip === void 0) {
      skip = false;
    }
    if (threshold === void 0) {
      threshold = 1;
    }
    cleanup();
    const elementRectForRootMargin = element.getBoundingClientRect();
    const {
      left,
      top,
      width,
      height
    } = elementRectForRootMargin;
    if (!skip) {
      onMove();
    }
    if (!width || !height) {
      return;
    }
    const insetTop = floor(top);
    const insetRight = floor(root.clientWidth - (left + width));
    const insetBottom = floor(root.clientHeight - (top + height));
    const insetLeft = floor(left);
    const rootMargin = -insetTop + "px " + -insetRight + "px " + -insetBottom + "px " + -insetLeft + "px";
    const options = {
      rootMargin,
      threshold: max(0, min(1, threshold)) || 1
    };
    let isFirstUpdate = true;
    function handleObserve(entries) {
      const ratio = entries[0].intersectionRatio;

      // The entry is a snapshot, so the reference may have moved since the
      // intersection was computed (under performance constraints, or between
      // consecutive frames of a multi-frame layout shift). The reported ratio
      // and the observed area are stale in that case and cannot be trusted to
      // detect subsequent movement, so refresh regardless of the ratio.
      if (!rectsAreEqual(elementRectForRootMargin, element.getBoundingClientRect())) {
        return refresh();
      }
      if (ratio !== threshold) {
        if (!isFirstUpdate) {
          return refresh();
        }
        if (!ratio) {
          // If the reference is clipped in place, the ratio is 0. Throttle
          // the refresh to prevent an infinite loop of updates.
          timeoutId = setTimeout(() => {
            refresh(false, 1e-7);
          }, 1000);
        } else {
          refresh(false, ratio);
        }
      }
      isFirstUpdate = false;
    }

    // Older browsers don't support a `document` as the root and will throw an
    // error.
    try {
      io = new IntersectionObserver(handleObserve, {
        ...options,
        // Handle <iframe>s
        root: root.ownerDocument
      });
    } catch (_e) {
      io = new IntersectionObserver(handleObserve, options);
    }
    io.observe(element);
  }
  const win = getWindow(element);
  // The window is a resize ancestor, so when `ancestorResize` is enabled its
  // listener already runs the update on resize. Here we only need to rebuild
  // the `IntersectionObserver` for the new root size, skipping a redundant
  // update. When `ancestorResize` is disabled, this becomes the sole update.
  const handleResize = () => refresh(ancestorResize);
  win.addEventListener('resize', handleResize);
  refresh(true);
  return () => {
    win.removeEventListener('resize', handleResize);
    cleanup();
  };
}

/**
 * Automatically updates the position of the floating element when necessary.
 * Should only be called when the floating element is mounted on the DOM or
 * visible on the screen.
 * @returns cleanup function that should be invoked when the floating element is
 * removed from the DOM or hidden from the screen.
 * @see https://floating-ui.com/docs/autoUpdate
 */
function autoUpdate(reference, floating, update, options) {
  if (options === void 0) {
    options = {};
  }
  const {
    ancestorScroll = true,
    ancestorResize = true,
    elementResize = typeof ResizeObserver === 'function',
    layoutShift = typeof IntersectionObserver === 'function',
    animationFrame = false
  } = options;
  const referenceEl = unwrapElement(reference);
  const ancestors = ancestorScroll || ancestorResize ? [...(referenceEl ? getOverflowAncestors(referenceEl) : []), ...(floating ? getOverflowAncestors(floating) : [])] : [];
  ancestors.forEach(ancestor => {
    ancestorScroll && ancestor.addEventListener('scroll', update);
    ancestorResize && ancestor.addEventListener('resize', update);
  });
  const cleanupIo = referenceEl && layoutShift ? observeMove(referenceEl, update, ancestorResize) : null;
  let reobserveFrame = -1;
  let resizeObserver = null;
  if (elementResize) {
    resizeObserver = new ResizeObserver(_ref => {
      let [firstEntry] = _ref;
      if (firstEntry && firstEntry.target === referenceEl && resizeObserver && floating) {
        // Prevent update loops when using the `size` middleware.
        // https://github.com/floating-ui/floating-ui/issues/1740
        resizeObserver.unobserve(floating);
        cancelAnimationFrame(reobserveFrame);
        reobserveFrame = requestAnimationFrame(() => {
          var _resizeObserver;
          (_resizeObserver = resizeObserver) == null || _resizeObserver.observe(floating);
        });
      }
      update();
    });
    if (referenceEl && !animationFrame) {
      resizeObserver.observe(referenceEl);
    }
    if (floating) {
      resizeObserver.observe(floating);
    }
  }
  let frameId;
  let prevRefRect = animationFrame ? getBoundingClientRect(reference) : null;
  if (animationFrame) {
    frameLoop();
  }
  function frameLoop() {
    const nextRefRect = getBoundingClientRect(reference);
    if (prevRefRect && !rectsAreEqual(prevRefRect, nextRefRect)) {
      update();
    }
    prevRefRect = nextRefRect;
    frameId = requestAnimationFrame(frameLoop);
  }
  update();
  return () => {
    var _resizeObserver2;
    ancestors.forEach(ancestor => {
      ancestorScroll && ancestor.removeEventListener('scroll', update);
      ancestorResize && ancestor.removeEventListener('resize', update);
    });
    cleanupIo == null || cleanupIo();
    (_resizeObserver2 = resizeObserver) == null || _resizeObserver2.disconnect();
    resizeObserver = null;
    if (animationFrame) {
      cancelAnimationFrame(frameId);
    }
  };
}

/**
 * Modifies the placement by translating the floating element along the
 * specified axes.
 * A number (shorthand for `mainAxis` or distance), or an axes configuration
 * object may be passed.
 * @see https://floating-ui.com/docs/offset
 */
const offset = offset$1;

/**
 * Optimizes the visibility of the floating element by shifting it in order to
 * keep it in view when it will overflow the clipping boundary.
 * @see https://floating-ui.com/docs/shift
 */
const shift = shift$1;

/**
 * Optimizes the visibility of the floating element by flipping the `placement`
 * in order to keep it in view when the preferred placement(s) will overflow the
 * clipping boundary. Alternative to `autoPlacement`.
 * @see https://floating-ui.com/docs/flip
 */
const flip = flip$1;

/**
 * Computes the `x` and `y` coordinates that will place the floating element
 * next to a given reference element.
 */
const computePosition = (reference, floating, options) => {
  // This caches the expensive `getClippingElementAncestors` function so that
  // multiple lifecycle resets re-use the same result. It only lives for a
  // single call. If other functions become expensive, we can add them as well.
  const cache = new Map();
  const mergedOptions = options != null ? options : {};
  const platformWithCache = {
    ...platform,
    ...mergedOptions.platform,
    _c: cache
  };
  return computePosition$1(reference, floating, {
    ...mergedOptions,
    platform: platformWithCache
  });
};

class Combobox {
  constructor(element) {
    this._destroyed = false;
    this.parent = element;
    this.element = this.parent.querySelector(
      "select, input"
    ) || element;
    this.mobile = window.matchMedia("(max-width: 768px)").matches;
    this.options = [];
    this.values = /* @__PURE__ */ new Set();
    this.focusedIndex = -1;
    this.panel = null;
    this.panelOpen = false;
    this.panelReady = Promise.resolve(false);
    this.popupRole = "listbox";
    this.optionRole = "option";
    this.triggerRole = "combobox";
    this.positionReference = null;
    this.matchReferenceWidth = false;
    this.elementKeydown = this.elementKeydown.bind(this);
    this.elementClick = this.elementClick.bind(this);
    this._documentClick = this._documentClick.bind(this);
    this._documentKeydown = this._documentKeydown.bind(this);
    this._panelPointerMove = this._panelPointerMove.bind(this);
    this._panelPointerDown = this._panelPointerDown.bind(this);
    this._optionClick = this._optionClick.bind(this);
    this._handleIntersection = this._handleIntersection.bind(this);
    this.placement = this.placement || "bottom-start";
    this.styles = { panel: STYLES.dropdown.panel };
    const data = { ...this.parent.dataset, ...this.element?.dataset };
    this.index = data.index;
    this.kind = data.kind || this.index || "default";
    this.placeholder = data.placeholder;
    this.preload = data.preload;
    this.multiple = data.multiple === void 0 ? void 0 : JSON.parse(data.multiple);
    this.creatable = data.creatable;
    this.formType = data.formType;
    this.includeUsers = data.includeUsers;
    this.permission = data.permission;
    this.name = this.element?.name || this.element?.id || this.index;
    this.id = this.element?.id || generateElementId("combobox");
  }
  init() {
    if (this._destroyed) return;
    if (!this.element) throw new Error("Element not found");
    this.element.autocomplete = "off";
    this.element.setAttribute("data-1p-ignore", "");
    this.element.setAttribute("aria-expanded", "false");
    this.element.setAttribute("aria-haspopup", this.popupRole);
    if (this.triggerRole) {
      this.element.setAttribute("role", this.triggerRole);
    } else {
      this.element.removeAttribute("role");
    }
    this.element.setAttribute("spellcheck", "false");
    if (this.placeholder && !this.element.placeholder) {
      this.element.placeholder = this.placeholder;
    }
    this._addElementHandlers();
    this._initElementObserver();
    this.parent.setAttribute("data-combobox-id", this.id);
    this.parent._lp_combobox = this;
    this.element.id = this.id;
  }
  _addElementHandlers() {
    if (this._elementHandlersAdded) return;
    this.element.addEventListener("keydown", this.elementKeydown);
    this.element.addEventListener("click", this.elementClick);
    this._elementHandlersAdded = true;
  }
  _removeElementHandlers() {
    if (!this._elementHandlersAdded) return;
    this.element.removeEventListener("keydown", this.elementKeydown);
    this.element.removeEventListener("click", this.elementClick);
    this._elementHandlersAdded = false;
  }
  _addDocumentHandlers() {
    if (this._documentHandlersAdded) return;
    document.addEventListener("click", this._documentClick, { capture: true });
    document.addEventListener("keydown", this._documentKeydown, {
      capture: true
    });
    this._documentHandlersAdded = true;
  }
  _removeDocumentHandlers() {
    if (!this._documentHandlersAdded) return;
    document.removeEventListener("click", this._documentClick, {
      capture: true
    });
    document.removeEventListener("keydown", this._documentKeydown, {
      capture: true
    });
    this._documentHandlersAdded = false;
  }
  _initElementObserver() {
    this._observer = new IntersectionObserver(this._handleIntersection, {
      threshold: 0
    });
    this._observer.observe(this.element);
  }
  _handleIntersection(entries) {
    entries.forEach((entry) => {
      if (!entry.isIntersecting && this.panelOpen) {
        this.hidePanel();
      }
    });
  }
  _addPanelHandlers() {
    if (this._panelHandlersAdded || !this.panel) return;
    this.panel.addEventListener("pointermove", this._panelPointerMove);
    this.panel.addEventListener("pointerdown", this._panelPointerDown);
    this.panel.addEventListener("click", this._optionClick);
    this._panelHandlersAdded = true;
  }
  _removePanelHandlers() {
    if (!this._panelHandlersAdded) return;
    this.panel?.removeEventListener("pointermove", this._panelPointerMove);
    this.panel?.removeEventListener("pointerdown", this._panelPointerDown);
    this.panel?.removeEventListener("click", this._optionClick);
    this._panelHandlersAdded = false;
  }
  _createPanel() {
    if (this._destroyed || this.panel) return;
    this.panel = document.createElement("div");
    this.panel.id = `${this.id}-panel`;
    this.panel.setAttribute("role", this.popupRole);
    this.panel.setAttribute("aria-labelledby", this.id);
    this.panel.className = this.styles.panel;
    this.panel.dataset.kind = this.kind;
    this.panel.dataset.visible = "false";
    this.element.setAttribute("aria-controls", this.panel.id);
    document.body.appendChild(this.panel);
  }
  _startAutoUpdate() {
    this._cleanupAutoUpdate();
    if (this._destroyed) return Promise.resolve(false);
    const reference = this.positionReference || this.element;
    const panel = this.panel;
    if (!panel) return Promise.resolve(false);
    let active = true;
    let positionRequest = 0;
    let readySettled = false;
    let resolveReady;
    let rejectReady;
    const ready = new Promise((resolve, reject) => {
      resolveReady = resolve;
      rejectReady = reject;
    });
    const settleReady = (positioned, error = null) => {
      if (readySettled) {
        if (error) captureError(error, panel);
        return;
      }
      readySettled = true;
      if (error) rejectReady(error);
      else resolveReady(positioned);
    };
    const cleanup = autoUpdate(reference, panel, () => {
      if (!active || this._destroyed || this.panel !== panel) return;
      const request = ++positionRequest;
      const middleware = [
        offset(4),
        // Try the opposite alignment before shifting away from the anchor.
        flip({ padding: 5 }),
        shift({ padding: 5 })
      ];
      if (this.matchReferenceWidth) {
        const { width } = reference.getBoundingClientRect();
        panel.style.minWidth = `${Math.ceil(width)}px`;
      } else if (this.element.classList.contains("w-full")) {
        const { width } = this.element.getBoundingClientRect();
        panel.style.width = `${Math.round(width)}px`;
      }
      computePosition(reference, panel, {
        // Reconsider the preferred placement after each resize or move.
        placement: this.placement,
        middleware
      }).then(({ x, y }) => {
        if (!active || this._destroyed || this.panel !== panel) {
          settleReady(false);
          return;
        }
        if (request !== positionRequest) return;
        Object.assign(panel.style, {
          left: `${x}px`,
          top: `${y}px`
        });
        settleReady(true);
      }).catch((error) => {
        if (!active || this._destroyed || this.panel !== panel) {
          settleReady(false);
          return;
        }
        if (request !== positionRequest) return;
        settleReady(false, error);
      });
    });
    this.cleanup = () => {
      active = false;
      cleanup();
      settleReady(false);
    };
    return ready;
  }
  _cleanupAutoUpdate() {
    if (this.cleanup) {
      this.cleanup();
      this.cleanup = null;
    }
  }
  _addCheckbox(option) {
    const id = option.dataset.id;
    const checkboxElement = primitives.checkbox({
      checked: id !== void 0 && this.values.has(id),
      kind: this.kind,
      label: false
    });
    checkboxElement.dataset.role = "option-checkbox";
    option.appendChild(checkboxElement);
    option.className = `${option.className} ${STYLES.dropdown.option.multiple}`.trim();
    option._checkbox = checkboxElement.querySelector("input");
  }
  _hasPanelContent(panel = this.panel) {
    return Boolean(
      panel?.querySelector(`[role='${this.optionRole}'], [data-role='empty']`)
    );
  }
  updatePanel(html) {
    if (this._destroyed) return false;
    if (!this.panel) this._createPanel();
    const panel = this.panel;
    if (!panel) return false;
    this.options = [];
    this.focusedIndex = -1;
    this.element.removeAttribute("aria-activedescendant");
    panel.innerHTML = html || "";
    if (!html) {
      this.hidePanel();
      return;
    }
    panel.querySelectorAll(`[role='${this.optionRole}']`).forEach((optionElt, index) => {
      optionElt.dataset.index = String(index);
      if (!optionElt.id) optionElt.id = `${panel.id}-opt-${index}`;
      if (this.items) {
        this.items[index].id = optionElt.id;
        this.options.push(this.items[index]);
      } else {
        const details = JSON.parse(
          optionElt.dataset.details || "{}"
        );
        const option = {
          ...optionElt.dataset,
          ...details
        };
        this.options.push(option);
      }
      if (this.multiple && optionElt.dataset.id) {
        this._addCheckbox(optionElt);
      }
    });
    if (!this._hasPanelContent(panel)) {
      this.hidePanel();
    }
  }
  showPanel() {
    if (this._destroyed) return Promise.resolve(false);
    const panel = this.panel;
    if (!panel || !this._hasPanelContent(panel)) {
      this.hidePanel();
      return Promise.resolve(false);
    }
    if (this.panelOpen) return this.panelReady;
    this.panelOpen = true;
    panel.classList.remove("hidden");
    panel.dataset.visible = "true";
    panel.dataset.positioned = "false";
    this.element.setAttribute("aria-expanded", "true");
    this.element.dataset.panel = "open";
    this._addPanelHandlers();
    this._addDocumentHandlers();
    const panelReady = Promise.resolve(this._startAutoUpdate()).then((positioned) => {
      if (positioned === false || this.panelReady !== panelReady || this.panel !== panel || !this.panelOpen) {
        return false;
      }
      panel.dataset.positioned = "true";
      document.querySelectorAll("[data-combobox-id]").forEach((combobox) => {
        if (combobox._lp_combobox && combobox._lp_combobox !== this) {
          combobox._lp_combobox.hidePanel();
        }
      });
      return true;
    }).catch((error) => {
      if (this.panelReady === panelReady && this.panel === panel) {
        this.hidePanel();
      }
      captureError(error, panel);
      return false;
    });
    this.panelReady = panelReady;
    return panelReady;
  }
  hidePanel() {
    const wasOpen = this.panelOpen;
    this.panelOpen = false;
    this.panelReady = Promise.resolve(false);
    this.panel?.classList.add("hidden");
    if (this.panel) {
      this.panel.dataset.visible = "false";
      this.panel.dataset.positioned = "false";
    }
    this.element.setAttribute("aria-expanded", "false");
    this.element.dataset.panel = "closed";
    this.unfocusOption();
    this._removePanelHandlers();
    this._removeDocumentHandlers();
    this._cleanupAutoUpdate();
    if (wasOpen) return true;
  }
  elementClick(event, hidePanel = true) {
    event.stopPropagation();
    if (this.panelOpen && hidePanel) {
      this.hidePanel();
    }
    this.element.focus();
  }
  elementKeydown(event) {
    const count = this.options.length;
    const next = () => this.focusedIndex >= count - 1 ? 0 : this.focusedIndex + 1;
    const prev = () => this.focusedIndex <= 0 ? count - 1 : this.focusedIndex - 1;
    switch (event.key) {
      case "ArrowDown":
        if (this.panelOpen && count > 0) {
          event.stopPropagation();
          event.preventDefault();
          this.focusOption(next());
        }
        break;
      case "ArrowUp":
        if (this.panelOpen && count > 0) {
          event.stopPropagation();
          event.preventDefault();
          this.focusOption(prev());
        }
        break;
      case "Enter": {
        if (this.panelOpen && this.focusedIndex >= 0) {
          event.stopPropagation();
          event.preventDefault();
          const option = this.focusedOption();
          if (option) this.selectOption(option);
        }
        break;
      }
      case "Tab":
        if (this.panelOpen) this.hidePanel();
        break;
    }
  }
  focusedOption() {
    if (this.focusedIndex < 0) return null;
    return this.panel?.querySelector(
      `[data-index="${this.focusedIndex}"]`
    ) ?? null;
  }
  focusOption(index) {
    const currentOption = this.focusedOption();
    if (currentOption) {
      this.unfocusOption(currentOption);
    }
    const option = this.panel?.querySelector(
      `[data-index="${index}"]`
    );
    if (!option) return;
    option.setAttribute("aria-selected", "true");
    option.scrollIntoView({ block: "nearest" });
    this.focusedIndex = Number.parseInt(option.dataset.index ?? "", 10);
    this.element.setAttribute("aria-activedescendant", option.id);
  }
  unfocusOption(option) {
    const currentOption = option || this.focusedOption();
    if (!currentOption) return;
    currentOption.setAttribute("aria-selected", "false");
    this.focusedIndex = -1;
    this.element.removeAttribute("aria-activedescendant");
  }
  _panelPointerDown(event) {
    event.preventDefault();
  }
  _documentClick(event) {
    if (this.panelOpen && event.target instanceof Node && !this.element.contains(event.target) && !this.panel?.contains(event.target)) {
      this.deactivate();
    }
  }
  _documentKeydown(event) {
    if (this.panelOpen && event.key === "Escape") {
      this.deactivate();
    }
  }
  _panelPointerMove(event) {
    if (!(event.target instanceof Element)) return;
    const option = event.target.closest(
      `[role="${this.optionRole}"]`
    );
    if (!option) return;
    const index = Number.parseInt(option.dataset.index ?? "", 10);
    if (index === this.focusedIndex) return;
    this.focusOption(index);
  }
  _optionClick(event) {
    if (!(event.target instanceof Element)) return;
    const option = event.target.closest(
      `[role="${this.optionRole}"]`
    );
    if (option) {
      event.stopPropagation();
      this.selectOption(option, event);
    }
  }
  show() {
    this.element.focus();
  }
  hide() {
    if (this.panelOpen) {
      this.hidePanel();
    }
  }
  deactivate() {
    this.hidePanel();
    this.element.dispatchEvent(new Event("deactivate", { bubbles: true }));
  }
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    this._removeElementHandlers();
    this._removePanelHandlers();
    this._removeDocumentHandlers();
    this._cleanupAutoUpdate();
    if (this._observer) {
      this._observer.disconnect();
      this._observer = null;
    }
    this.hidePanel();
    if (this.panel) this.panel.remove();
    this.panel = null;
    this.element.removeAttribute("aria-controls");
    this.parent.removeAttribute("data-combobox-id");
    if (this.parent._lp_combobox === this) {
      delete this.parent._lp_combobox;
    }
  }
}

function hasInputValue(event) {
  const { target } = event;
  return target != null && "value" in target && typeof target.value === "string";
}
class RemoteQueryCombobox extends Combobox {
  constructor(element, { queryWait = 200 } = {}) {
    super(element);
    this.queries = new QueryLifecycle();
    this._queryPending = false;
    this._queryInput = this._queryInput.bind(this);
    this._debouncedInput = debounce((event) => {
      const result = this._input(event);
      if (result?.catch) {
        result.catch((error) => captureError(error, this.element));
      }
    }, queryWait);
  }
  init() {
    if (this._destroyed) return;
    this.element.addEventListener("input", this._queryInput);
    super.init();
    this.element.setAttribute("aria-busy", "false");
  }
  _queryInput(event) {
    if (this._destroyed || !hasInputValue(event)) return;
    const inputValue = event.target.value;
    this.queries.invalidate();
    this._queryPending = true;
    this.element.setAttribute("aria-busy", "true");
    super.hidePanel();
    if (event.target === this.element) {
      this.element.value = inputValue;
    }
    this._debouncedInput(event);
  }
  invalidateQuery() {
    this.queries.invalidate();
    this._queryPending = false;
    this.element.setAttribute("aria-busy", "false");
  }
  settleQueryInput({ clear = false } = {}) {
    this.invalidateQuery();
    if (clear) this.clearQueryResults();
  }
  clearQueryResults() {
    this.options = [];
    this.focusedIndex = -1;
    this.element.removeAttribute("aria-activedescendant");
    this.panel?.replaceChildren();
    super.hidePanel();
  }
  runQuery(key, loader, publisher, {
    getCurrentKey = () => this.element.value.trim(),
    cancelTransport = true
  } = {}) {
    if (this._destroyed) return Promise.resolve(false);
    this._queryPending = true;
    this.element.setAttribute("aria-busy", "true");
    let activeToken = null;
    return this.queries.run(
      key,
      (token) => {
        activeToken = token;
        return loader(token);
      },
      (result, token) => {
        this._queryPending = false;
        this.element.setAttribute("aria-busy", "false");
        return publisher(result, token);
      },
      { getCurrentKey, cancelTransport }
    ).catch((error) => {
      if (this.queries.isCurrent(activeToken, getCurrentKey())) {
        this._queryPending = false;
        this.element.setAttribute("aria-busy", "false");
      }
      throw error;
    });
  }
  showPanel() {
    if (this._queryPending) return Promise.resolve(false);
    return super.showPanel();
  }
  hidePanel() {
    this.invalidateQuery();
    return super.hidePanel();
  }
  destroy() {
    if (this._destroyed) return;
    this._debouncedInput.cancel();
    this.queries.destroy();
    this._queryPending = false;
    this.element.removeEventListener("input", this._queryInput);
    super.destroy();
    this.element.removeAttribute("aria-busy");
  }
}

const SEARCH_ENTITY_PATTERN = /&(#(?:x[0-9a-f]+|\d+)|amp|apos|gt|lt|quot);/gi;
const SEARCH_ENTITIES = Object.freeze({
  amp: "&",
  apos: "'",
  gt: ">",
  lt: "<",
  quot: '"'
});
const decodeSearchEntities = (text) => String(text).replace(SEARCH_ENTITY_PATTERN, (entity, name2) => {
  if (!name2.startsWith("#"))
    return SEARCH_ENTITIES[name2.toLowerCase()] ?? entity;
  const hexadecimal = name2[1]?.toLowerCase() === "x";
  const value = Number.parseInt(
    name2.slice(hexadecimal ? 2 : 1),
    hexadecimal ? 16 : 10
  );
  if (!Number.isInteger(value) || value <= 0 || value > 1114111 || value >= 55296 && value <= 57343) {
    return "\uFFFD";
  }
  return String.fromCodePoint(value);
});
const appendHighlightedSearchText = (element, markup) => {
  let target = element;
  for (const part of String(markup).split(/(<\/?b>)/gi)) {
    if (part.toLowerCase() === "<b>") {
      target = document.createElement("b");
      element.appendChild(target);
    } else if (part.toLowerCase() === "</b>") {
      target = element;
    } else if (part) {
      target.appendChild(document.createTextNode(decodeSearchEntities(part)));
    }
  }
};
const option = (details) => {
  const option2 = document.createElement("div");
  option2.className = STYLES.dropdown.option.flow;
  option2.setAttribute("role", "option");
  if (details.disabled) {
    option2.setAttribute("aria-disabled", "true");
    option2.classList.add("opacity-50", "cursor-not-allowed");
  }
  if (details.id) {
    option2.id = details.id;
    option2.dataset.id = details.id;
  }
  const decoration = details.icon && icon(details);
  if (decoration) option2.appendChild(decoration);
  option2.append(formatting.name(details));
  return option2.outerHTML;
};
const icon = (details) => {
  const iconType = details.icon || details.kind || details.type;
  if (iconType) {
    const container = document.createElement("span");
    container.className = "text-kind-default";
    container.dataset.kind = String(details.kind || details.index);
    const iconElement = container.appendChild(document.createElement("span"));
    setIcon(iconElement, iconType, STYLES.dropdown.icon);
    return container;
  }
};
const name = (details) => {
  const p1 = document.createElement("p");
  const decoration = icon(details);
  if (decoration) p1.append(decoration);
  p1.append(formatting.name(details));
  return p1;
};
const search$1 = (result) => {
  const option2 = document.createElement("div");
  option2.className = STYLES.dropdown.search.link;
  option2.setAttribute("role", "option");
  option2.dataset.result = JSON.stringify(result);
  option2.dataset.url = String(result.url);
  option2.appendChild(name(result.details));
  if (result.form_field) {
    const p2 = document.createElement("p");
    p2.className = `italic font-normal text-base-default`;
    const fieldSpan = document.createElement("span");
    fieldSpan.className = "font-semibold text-form-default";
    fieldSpan.textContent = `${result.form_field}:`;
    p2.appendChild(fieldSpan);
    const formValueText = document.createElement("span");
    formValueText.className = "ml-1";
    formValueText.textContent = `${result.form_value}`;
    p2.appendChild(formValueText);
    option2.appendChild(p2);
  }
  if (result.text) {
    const p3 = document.createElement("p");
    p3.className = `italic font-normal text-base-default`;
    appendHighlightedSearchText(p3, result.text);
    option2.appendChild(p3);
  }
  return option2.outerHTML;
};
const facet = (details) => {
  const option2 = document.createElement("div");
  option2.className = `${STYLES.dropdown.search.result}`;
  option2.setAttribute("role", "option");
  option2.dataset.details = JSON.stringify(details);
  option2.dataset.id = String(details.id);
  option2.dataset.name = String(details.name);
  option2.dataset.kind = String(details.kind);
  option2.appendChild(name(details));
  return option2.outerHTML;
};
class Results {
  constructor(index) {
    this.index = index;
    this.added = [];
  }
  get options() {
    const key = `recent-${this.index}`;
    const recent = localStore.getJSON(key, []);
    if (Array.isArray(recent)) return recent;
    localStore.remove(key);
    return [];
  }
  add(option2) {
    this.added.unshift(option2);
  }
  save(option2) {
    const recent = this.options;
    let filtered;
    if (this.index === "search" && option2.dataset.result) {
      filtered = recent.filter((o) => o.url !== option2.dataset.url);
      const result = JSON.parse(option2.dataset.result);
      result.url = option2.dataset.url;
      filtered.unshift(result);
    } else if (option2.dataset.id) {
      filtered = recent.filter((o) => o.id !== option2.dataset.id);
      const details = JSON.parse(String(option2.dataset.details));
      filtered.unshift(details);
    }
    if (Array.isArray(filtered)) {
      localStore.setJSON(`recent-${this.index}`, filtered.slice(0, 10));
    }
  }
  unique(options) {
    return options.filter(
      (o, index, self) => index === self.findIndex((t) => t.id === o.id)
    );
  }
  create(items = []) {
    let options = items;
    if (!items.length) {
      options = this.unique([...this.added, ...this.options]).slice(0, 10);
    }
    if (!options.length) return "";
    if (this.index === "search") {
      return options.map(search$1).join("");
    } else if (this.index) {
      return options.map(facet).join("");
    } else {
      return options.map(option).join("");
    }
  }
}

class SearchBox extends RemoteQueryCombobox {
  constructor(element) {
    super(element);
    this.index = "search";
    this.results = new Results(this.index);
    this.placement = "bottom-end";
    this.endpoints = ENDPOINTS.search;
  }
  init() {
    this.styles.panel = `${STYLES.dropdown.panel} right-0 w-64 sm:w-96 mt-2`;
    super.init();
    this.updatePanel(this.results.create());
  }
  _input(event) {
    const query = event.target.value.trim();
    if (query.length > 1) {
      return this._search(query);
    } else if (query.length === 0) {
      this.settleQueryInput();
      this.updatePanel(this.results.create());
      return this.showPanel();
    }
    this.settleQueryInput({ clear: true });
  }
  elementClick(event) {
    super.elementClick(event);
    this.showPanel();
  }
  _search(query) {
    const params = new URLSearchParams();
    params.set("q", query);
    return this.runQuery(
      query,
      (token) => request.get(this.endpoints.bar, params, {
        signal: token.signal
      }),
      (response) => {
        if (response?.ok) {
          this.updatePanel(response.results || null);
        } else {
          this.clearQueryResults();
        }
        return this.showPanel();
      }
    );
  }
  /**
   * @template nav.html::search_results
   */
  selectOption(option) {
    const { url } = option.dataset;
    if (!url) return;
    this.results.save(option);
    this.hidePanel();
    window.location.href = url;
  }
  elementKeydown(event) {
    super.elementKeydown(event);
    if (event.defaultPrevented) return;
    if (event.key === "Enter") {
      event.preventDefault();
      event.stopPropagation();
      const params = new URLSearchParams();
      params.set("q", this.element.value);
      if (this.element.value) {
        window.location.href = `${this.endpoints.page}?${params.toString()}`;
      }
    }
  }
}

var search = /*#__PURE__*/Object.freeze({
  __proto__: null,
  SearchBox: SearchBox
});

class Dropdown extends Combobox {
  init(menu) {
    this.placement = menu.placement ?? "bottom-start";
    this.items = menu.items || [];
    this.styles = { ...this.styles, ...menu.styles || {} };
    this.popupRole = menu.popupRole || this.popupRole;
    this.optionRole = menu.optionRole || this.optionRole;
    if ("positionReference" in menu) {
      this.positionReference = menu.positionReference;
    }
    this.matchReferenceWidth = menu.matchReferenceWidth ?? this.matchReferenceWidth;
    if ("triggerRole" in menu) this.triggerRole = menu.triggerRole;
    this._loadOptions = menu.loadOptions || (async () => this.items);
    this.emptyHtml = menu.emptyHtml ?? null;
    this.onShow = menu.onShow || null;
    this.onHide = menu.onHide || null;
    super.init(menu);
    return this;
  }
  _createDropdownButton(item) {
    const itemButton = document.createElement("button");
    itemButton.className = STYLES.dropdown.option.action;
    itemButton.type = "button";
    itemButton.setAttribute("role", this.optionRole);
    if (item.icon) {
      const icon = document.createElement("span");
      icon.dataset.kind = item.kind;
      setIcon(icon, item.icon, `${STYLES.dropdown.icon} text-kind-default`);
      itemButton.appendChild(icon);
    }
    const text = document.createElement("span");
    text.textContent = item.name ?? null;
    itemButton.appendChild(text);
    return itemButton.outerHTML;
  }
  _emptyMarkup() {
    const markup = typeof this.emptyHtml === "function" ? this.emptyHtml() : this.emptyHtml;
    return markup ? markup.trim() : "";
  }
  _renderOptions() {
    const itemsHtml = this.items.map((item) => item.html || this._createDropdownButton(item)).join("");
    const emptyHtml = this._emptyMarkup();
    const html = `${itemsHtml}${emptyHtml}`;
    if (!html) {
      this.updatePanel("");
      return;
    }
    this.updatePanel(html);
  }
  async showPanel() {
    const items = await this._loadOptions();
    if (items !== void 0) this.items = items;
    this._renderOptions();
    const wasOpen = this.panelOpen;
    const opened = await super.showPanel();
    if (!wasOpen && opened) this.onShow?.();
    return opened;
  }
  selectOption(option, event = null) {
    const item = this.items[Number.parseInt(option.dataset.index ?? "", 10)];
    const closeOnClick = typeof item?.closeOnClick === "function" ? item.closeOnClick(option, event) : item?.closeOnClick !== false;
    if (closeOnClick) this.hidePanel();
    if (item.onClick) {
      item.onClick(option, event);
    }
  }
  addOption(option) {
    this.items.splice(0, 0, option);
    this._renderOptions();
  }
  removeOptions(identifiers) {
    this.hidePanel();
    this.items = this.items.filter((item) => !identifiers.includes(item.id));
    this._renderOptions();
  }
  updateOptions(options = []) {
    this.items = Array.isArray(options) ? options : [];
    this._renderOptions();
    if (!this.items.length && !this._emptyMarkup() && this.panelOpen) {
      this.hidePanel();
      return;
    }
    if (this.panelOpen) {
      void super.showPanel();
    }
  }
  elementClick(event) {
    event.stopPropagation();
    event.preventDefault();
    this.panelOpen ? this.hidePanel() : void this.showPanel();
  }
  hidePanel() {
    const hidden = super.hidePanel();
    if (hidden) this.onHide?.();
    this.element.blur();
  }
}

var dropdown = /*#__PURE__*/Object.freeze({
  __proto__: null,
  Dropdown: Dropdown
});

class EntityMenu {
  constructor(view) {
    this.view = view;
    this.dropdowns = /* @__PURE__ */ new Set();
  }
  _items(container) {
    const entityKey = container.closest("[data-key]")?.dataset.key;
    return Array.from(
      container.querySelectorAll(
        ":scope > [data-role='menu-items'] > [data-menu-item]"
      )
    ).filter((item) => !item.disabled && item.dataset.visible !== "false").map((source) => {
      const option = source.cloneNode(true);
      option.hidden = false;
      option.removeAttribute("id");
      option.setAttribute("role", "menuitem");
      option.querySelectorAll("[id]").forEach((element) => {
        element.removeAttribute("id");
      });
      if (entityKey) option.dataset.entityKey = entityKey;
      return {
        html: option.outerHTML,
        onClick: () => source.isConnected && source.click()
      };
    });
  }
  toggle(container) {
    if (!container) return;
    this._prune();
    const trigger = container.querySelector(
      ":scope > [data-role='menu-trigger']"
    );
    const items = this._items(container);
    if (!trigger || items.length === 0) return;
    const title = container.closest("[data-menu-anchor]")?.querySelector("[data-role='title']");
    const dropdown = new Dropdown(trigger).init({
      items,
      loadOptions: async () => this._items(container),
      placement: "bottom-start",
      positionReference: title || trigger,
      matchReferenceWidth: true,
      styles: { panel: STYLES.dropdown.menu },
      popupRole: "menu",
      optionRole: "menuitem",
      triggerRole: null
    });
    this.dropdowns.add(dropdown);
    return dropdown.showPanel();
  }
  _prune() {
    for (const dropdown of this.dropdowns) {
      if (dropdown.element.isConnected) continue;
      dropdown.destroy();
      this.dropdowns.delete(dropdown);
    }
  }
  destroy() {
    this.dropdowns.forEach((dropdown) => {
      dropdown.destroy();
    });
    this.dropdowns.clear();
    this.view = null;
  }
}

var entityMenu = /*#__PURE__*/Object.freeze({
  __proto__: null,
  EntityMenu: EntityMenu
});

export { Combobox as C, Dropdown as D, EntityMenu as E, Results as R, SearchBox as S, RemoteQueryCombobox as a, autoUpdate as b, computePosition as c, search as d, dropdown as e, flip as f, entityMenu as g, offset as o, shift as s };
