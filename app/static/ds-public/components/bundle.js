/* ds-public: the four components the studio uses, when the brand design system is not installed. The interface finds a design
   system by the suffix of its global (DesignSystem_9fde59): this one is NeutralDesignSystem_9fde59.
   Same names and props as there: Button {variant, size, ...a button's own}, Badge {tone}, Callout {tone, label}, Eyebrow. */
(function () {
  "use strict";
  const h = React.createElement;
  function Button({ variant = "primary", size = "md", type = "button", className, children, ...rest }) {
    return h("button", { type, className: "dsp-btn" + (className ? " " + className : ""), "data-variant": variant, "data-size": size, ...rest }, children);
  }
  function Badge({ tone, children }) {
    return h("span", { className: "dsp-badge", "data-tone": tone }, children);
  }
  function Callout({ tone, label, children }) {
    return h("div", { className: "dsp-callout", "data-tone": tone }, label && h("p", { className: "dsp-callout-label" }, label), h("div", null, children));
  }
  function Eyebrow({ children }) {
    return h("span", { className: "dsp-eyebrow" }, children);
  }
  window.NeutralDesignSystem_9fde59 = { Button, Badge, Callout, Eyebrow };
})();
