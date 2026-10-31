;; ============================================================
;; Python 查询集（定义 + 调用 + 导入）
;;
;; 设计原则（所有者 2026-10-31）：
;;   · 有限枚举：只列常见写法，⛔ 不做通用搜索、不下钻
;;   · 加一种写法 = 加一条语句（零代码风险）
;;
;; 覆盖：
;;   def f():            函数
;;   async def f():      异步函数（同样是 function_definition）
;;   class A:            类
;;   a.f()               属性调用
;;   f()                 直接调用
;;   import x / from x import y
;;
;; 主动放弃：
;;   装饰器包装后的名字（取 def 的名字，不追装饰器）
;;   lambda 里的定义（不构成作用域）
;;   __getattr__ 之类的动态分发
;; ============================================================

;; ------------------------------------------------------------ 定义
(function_definition name: (identifier) @def.function.name) @def.function
(class_definition name: (identifier) @def.class.name) @def.class

;; ------------------------------------------------------------ 继承
;; class D(Base, Mixin)   ⇒ 每个基类一条 extends
(class_definition
  superclasses: (argument_list (identifier) @ext.base)) @ext.owner

;; ------------------------------------------------------------ 导入
(import_statement) @imp
(import_from_statement) @imp

;; ------------------------------------------------------------ 调用
;; 直接调用  f()
(call function: (identifier) @call.direct.name) @call.direct

;; 属性调用  a.f() / self.f() / pkg.mod.f()
(call
  function: (attribute
    object: (_) @call.member.receiver
    attribute: (identifier) @call.member.name)) @call.member
