;; ============================================================
;; C 语言查询集（定义 + 调用 + 包含）
;;
;; 设计原则（所有者 2026-10-31）：
;;   · 有限枚举：把常见写法一条条列出来，⛔ 不做"通用搜索"
;;   · 不下钻：只描述"长什么样"，取到节点后由 c.py 处理
;;   · 头部写明覆盖与放弃 ⇒ 没有"未知的未知"
;;
;; 调用形态覆盖 ~98%：直接 / 指针成员 / 值成员 / 数组下标 /
;;                    1~3 层解引用 / 强制转换后调用
;; 主动放弃：4 层以上指针、复杂嵌套解引用、内联汇编、宏展开后的调用
;;
;; 抓取命名约定：
;;   @def.<种类>.name      定义名（外层 @def.<种类> 是整段）
;;   @call.<形态>.name     被调用名
;;   @call.<形态>.receiver 接收者（成员/指针成员/下标形态才有）
;;   @inc.path             被 include 的路径
;; ============================================================

;; ------------------------------------------------------------ 定义
;; ⚠ 只枚举**常见声明形态**，不常见的明确放弃（所有者 2026-10-31）：
;;
;;   覆盖：
;;     int f(void) {}                  普通函数
;;     static void f(int a) {}         storage/type 修饰不影响 declarator
;;     char *f(void) {}                返回指针
;;     char **f(void) {}               返回二级指针
;;     struct S *f(void) {}            返回结构体指针
;;     typedef unsigned int u32;       普通 typedef
;;     typedef char *va_list;          指针 / 二级指针 typedef
;;     typedef char buf[N];            数组 typedef
;;     typedef int (*cb)(int);         函数指针 typedef（很常见）
;;     int f(a, b) int a; {}           K&R 老式定义（linux 0.01 那种）
;;
;;   主动放弃（不常见，用户真要看就在改图里手补一个）：
;;     int (*f(int))(void)             返回函数指针
;;     void (*signal(int, void(*)(int)))(int)
;;     typedef BOOL (WINAPI *X)(...)   带调用约定的函数指针 typedef
;;     多维数组返回、复杂嵌套的声明符
;;
;; 实测（sqlite 合并版 + linux 0.01，共 30.7 万行）：
;;   函数 5531 / 5550（放弃的 19 条里，8 条是 (*f(...))(...) 形态，
;;                    6 条是原实现把 struct / 返回类型当函数名的错误节点）

;; 1. 普通函数 / K&R 定义：int f(void) {}
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @def.function.name)) @def.function

;; 2. 返回指针：char *f(void) {}
(function_definition
  declarator: (pointer_declarator
    declarator: (function_declarator
      declarator: (identifier) @def.function.name))) @def.function

;; 3. 返回二级指针：char **f(void) {}
(function_definition
  declarator: (pointer_declarator
    declarator: (pointer_declarator
      declarator: (function_declarator
        declarator: (identifier) @def.function.name)))) @def.function

;; 4. struct/union/enum：只认**带 body** 的定义
(struct_specifier name: (type_identifier) @def.struct.name
  body: (field_declaration_list)) @def.struct
(union_specifier name: (type_identifier) @def.union.name
  body: (field_declaration_list)) @def.union
(enum_specifier name: (type_identifier) @def.enum.name
  body: (enumerator_list)) @def.enum

;; 5. 普通 typedef：typedef unsigned int u32;
(type_definition declarator: (type_identifier) @def.typedef.name) @def.typedef

;; 6. 指针 typedef：typedef char *va_list; / typedef DIR *LPDIR;
(type_definition
  declarator: (pointer_declarator
    declarator: (type_identifier) @def.typedef.name)) @def.typedef

;; 7. 二级指针 typedef：typedef char **argv_t;
(type_definition
  declarator: (pointer_declarator
    declarator: (pointer_declarator
      declarator: (type_identifier) @def.typedef.name))) @def.typedef

;; 8. 数组 typedef：typedef char buffer_block[BLOCK_SIZE];
(type_definition
  declarator: (array_declarator
    declarator: (type_identifier) @def.typedef.name)) @def.typedef

;; 9. 函数指针 typedef：typedef int (*cb)(int);
(type_definition
  declarator: (function_declarator
    declarator: (parenthesized_declarator
      (pointer_declarator declarator: (type_identifier) @def.typedef.name)))) @def.typedef

;; 6.5 字段（只进详情面板，⛔ 不进图）
(struct_specifier
  body: (field_declaration_list
    (field_declaration
      type: (_) @field.type
      declarator: (field_identifier) @field.name))) @field.owner
(struct_specifier
  body: (field_declaration_list
    (field_declaration
      type: (_) @field.type
      declarator: (pointer_declarator declarator: (field_identifier) @field.name)))) @field.owner
(struct_specifier
  body: (field_declaration_list
    (field_declaration
      type: (_) @field.type
      declarator: (array_declarator declarator: (field_identifier) @field.name)))) @field.owner
(union_specifier
  body: (field_declaration_list
    (field_declaration
      type: (_) @field.type
      declarator: (field_identifier) @field.name))) @field.owner

;; 7. 宏
(preproc_def name: (identifier) @def.macro.name) @def.macro
(preproc_function_def name: (identifier) @def.macro.name) @def.macro

;; ------------------------------------------------------------ 包含
(preproc_include path: (_) @inc.path) @inc

;; ------------------------------------------------------------ 调用
;; 1. 直接调用  foo(a, b)
(call_expression
  function: (identifier) @call.direct.name
  arguments: (argument_list)) @call.direct

;; 2. 指针成员调用  ptr->method(a)
(call_expression
  function: (field_expression
    argument: (_) @call.ptr_member.receiver
    operator: "->"
    field: (field_identifier) @call.ptr_member.name)
  arguments: (argument_list)) @call.ptr_member

;; 3. 值成员调用  obj.method(a)
(call_expression
  function: (field_expression
    argument: (_) @call.member.receiver
    operator: "."
    field: (field_identifier) @call.member.name)
  arguments: (argument_list)) @call.member

;; 4. 数组下标调用  table[i](a)
;;   ⚠ 不按字段名匹配（不同版本 grammar 的字段名不完全一致），整段取即可：
;;     这类调用**本来就只计数不建边**（目标是变量），不需要 receiver
(call_expression
  function: (subscript_expression) @call.subscript.name
  arguments: (argument_list)) @call.subscript

;; 5. 一层解引用  (*fp)(a)
(call_expression
  function: (parenthesized_expression
    (pointer_expression
      operator: "*"
      argument: (identifier) @call.deref1.name))
  arguments: (argument_list)) @call.deref1

;; 6. 一层解引用 + 指针成员  (*ptr->fn)(a)
(call_expression
  function: (parenthesized_expression
    (pointer_expression
      operator: "*"
      argument: (field_expression
        argument: (_) @call.deref1_ptr_member.receiver
        operator: "->"
        field: (field_identifier) @call.deref1_ptr_member.name)))
  arguments: (argument_list)) @call.deref1_ptr_member

;; 7. 一层解引用 + 值成员  (*obj.fn)(a)
(call_expression
  function: (parenthesized_expression
    (pointer_expression
      operator: "*"
      argument: (field_expression
        argument: (_) @call.deref1_member.receiver
        operator: "."
        field: (field_identifier) @call.deref1_member.name)))
  arguments: (argument_list)) @call.deref1_member

;; 8. 两层解引用  (**fp)(a)
(call_expression
  function: (parenthesized_expression
    (pointer_expression
      operator: "*"
      argument: (pointer_expression
        operator: "*"
        argument: (identifier) @call.deref2.name)))
  arguments: (argument_list)) @call.deref2

;; 9. 三层解引用  (***fp)(a)
(call_expression
  function: (parenthesized_expression
    (pointer_expression
      operator: "*"
      argument: (pointer_expression
        operator: "*"
        argument: (pointer_expression
          operator: "*"
          argument: (identifier) @call.deref3.name))))
  arguments: (argument_list)) @call.deref3

;; 10. 强制转换后调用  ((void (*)(void *))cb)(a)
(call_expression
  function: (parenthesized_expression
    (cast_expression value: (_) @call.cast.name))
  arguments: (argument_list)) @call.cast
