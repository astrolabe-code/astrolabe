;; ============================================================
;; Java 查询集（定义 + 调用 + 导入）
;;
;; 覆盖：
;;   class / interface / enum / record   类型
;;   method_declaration                  方法（含 static / 泛型）
;;   constructor_declaration             构造器（也算方法）
;;   a.m() / this.m() / Class.m()        调用
;;   import a.b.C;
;;
;; 主动放弃：
;;   lambda 体、匿名内部类里的方法（不构成命名作用域）
;;   可变参数/泛型边界不影响识别，但注解处理器生成的方法不可见
;; ============================================================

;; ------------------------------------------------------------ 定义
(class_declaration name: (identifier) @def.class.name) @def.class
(interface_declaration name: (identifier) @def.interface.name) @def.interface
(enum_declaration name: (identifier) @def.enum.name) @def.enum
(record_declaration name: (identifier) @def.record.name) @def.record

(method_declaration name: (identifier) @def.method.name) @def.method
(constructor_declaration name: (identifier) @def.method.name) @def.method

;; ------------------------------------------------------------ 继承 / 实现
;; class D extends Base            ⇒ extends
(class_declaration superclass: (superclass (type_identifier) @ext.base)) @ext.owner
;; class D implements I1, I2       ⇒ implements
(class_declaration interfaces: (super_interfaces (type_list (type_identifier) @impl.base))) @impl.owner
;; interface I extends J           ⇒ extends（接口继承接口）
(interface_declaration
  (extends_interfaces (type_list (type_identifier) @ext.base))) @ext.owner

;; ------------------------------------------------------------ 字段
;; private int x;  /  private String name;
(class_declaration
  body: (class_body
    (field_declaration
      type: (_) @field.type
      declarator: (variable_declarator name: (identifier) @field.name)))) @field.owner

;; ------------------------------------------------------------ 导入
(import_declaration) @imp

;; ------------------------------------------------------------ 调用
;; method_invocation 的 callee 在 name 字段，接收者在 object 字段 ——
;; 两者都要抓，交给 java.py 拼（`a.m()` 与裸 `m()` 必须分开）
(method_invocation) @call.invocation
