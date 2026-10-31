;; ============================================================
;; C++ 查询集（定义 + 调用 + 包含）
;;
;; 覆盖：
;;   int f(){} / int C::f(){}        函数与方法
;;   int& f(){} / T&& f(){}          引用返回
;;   ~C(){}                          析构
;;   operator== / operator bool()    运算符重载与转换运算符
;;   using Alias = int;              using 别名
;;   template<T> struct Box<T*>{}    模板特化
;;   class / struct / union / enum   类型
;;   namespace ns {}                 命名空间（当作 module 处理）
;;   #define F(x)                    宏
;;   f() / obj.f() / p->f() / ns::f()
;;   #include <x>
;;
;; 主动放弃：
;;   模板特化、宏生成的定义、`int (*f(int))(void)` 这类罕见声明符
;;   （与 c.scm 同一口径）
;; ============================================================

;; ------------------------------------------------------------ 定义
;; ⚠ 名字可能是 `identifier`（自由函数）也可能是 `field_identifier`（类内方法）
;;   —— 实测：只写 identifier 会漏掉**所有类内定义的方法**（fmt 上漏了 1263 个）

;; 普通函数 / 类内方法：int f() {} / int C::f() 在类里定义的
(function_definition
  declarator: (function_declarator
    declarator: [(identifier) (field_identifier)] @def.function.name)) @def.function

;; 返回指针：char *f() {}
(function_definition
  declarator: (pointer_declarator
    declarator: (function_declarator
      declarator: [(identifier) (field_identifier)] @def.function.name))) @def.function

;; 带作用域的成员定义：int C::f() {}  ← 类外定义，常见
(function_definition
  declarator: (function_declarator
    declarator: (qualified_identifier
      scope: (_) @def.function.scope
      name: [(identifier) (field_identifier)] @def.function.name))) @def.function

;; 引用返回：int& f() / const T& f() / T&& f()
(function_definition
  declarator: (reference_declarator
    (function_declarator
      declarator: [(identifier) (field_identifier)] @def.function.name))) @def.function

;; 析构：~C()
(function_definition
  declarator: (function_declarator
    declarator: (destructor_name) @def.function.name)) @def.function

;; 运算符重载：bool operator==(const C&)
(function_definition
  declarator: (function_declarator
    declarator: (operator_name) @def.function.name)) @def.function

;; 转换运算符：operator bool() const / operator Action<F>() const
;;   ⚠ 名字只取 `operator <类型>`：operator_cast 整段会带上 `() const`，
;;     那样节点名会变成 "operator Action<F>() const"（难看且对不上调用点）
(function_definition
  declarator: (operator_cast type: (_))) @def.operator

(class_specifier name: (type_identifier) @def.class.name
  body: (field_declaration_list)) @def.class

;; 模板特化：template <typename T> struct Box<T*> { }
(class_specifier name: (template_type) @def.class.name
  body: (field_declaration_list)) @def.class
(struct_specifier name: (template_type) @def.struct.name
  body: (field_declaration_list)) @def.struct

;; using 别名：using Alias = int;
(alias_declaration name: (type_identifier) @def.alias.name) @def.alias
(struct_specifier name: (type_identifier) @def.struct.name
  body: (field_declaration_list)) @def.struct
(union_specifier name: (type_identifier) @def.union.name
  body: (field_declaration_list)) @def.union
(enum_specifier name: (type_identifier) @def.enum.name
  body: (enumerator_list)) @def.enum

(namespace_definition name: (namespace_identifier) @def.namespace.name) @def.namespace

;; ------------------------------------------------------------ 继承
;; class D : public Base, private Other   ⇒ 每个基类一条 extends
;;   ⚠ base_class_clause 没有字段名，是匿名子节点（只能用位置匹配）
(class_specifier (base_class_clause (type_identifier) @ext.base)) @ext.owner

;; ------------------------------------------------------------ 字段
(class_specifier
  body: (field_declaration_list
    (field_declaration
      type: (_) @field.type
      declarator: (field_identifier) @field.name))) @field.owner
(class_specifier
  body: (field_declaration_list
    (field_declaration
      type: (_) @field.type
      declarator: (pointer_declarator declarator: (field_identifier) @field.name)))) @field.owner
(struct_specifier
  body: (field_declaration_list
    (field_declaration
      type: (_) @field.type
      declarator: (field_identifier) @field.name))) @field.owner

(preproc_function_def name: (identifier) @def.macro.name) @def.macro
(preproc_def name: (identifier) @def.macro.name) @def.macro

;; ------------------------------------------------------------ 包含
(preproc_include path: (_) @inc.path) @inc

;; ------------------------------------------------------------ 调用
;; 直接：f()
(call_expression
  function: (identifier) @call.direct.name) @call.direct

;; 成员：obj.f() / p->f()
(call_expression
  function: (field_expression
    argument: (_) @call.member.receiver
    field: (field_identifier) @call.member.name)) @call.member

;; 限定：ns::f() / C::f() / Box<T>::f()
;;   ⚠ scope 用通配 —— 模板实例、嵌套类都是合法作用域（旧版只认 namespace，漏很多）
(call_expression
  function: (qualified_identifier
    scope: (_) @call.qualified.receiver
    name: [(identifier) (field_identifier) (template_function)] @call.qualified.name)) @call.qualified

;; 模板函数调用：f<int>(x)
(call_expression
  function: (template_function
    name: (identifier) @call.template.name)) @call.template

;; 模板成员调用：obj.f<int>(x)
(call_expression
  function: (field_expression
    argument: (_) @call.member_template.receiver
    field: (template_method
      name: (field_identifier) @call.member_template.name))) @call.member_template
