"""Rule extraction with clarification instead of invented business defaults."""
import re

DEPARTMENTS=('信息技术部','研发部','综合管理部')
ITEMS=('笔记本电脑','台式电脑','显示器','打印机','办公设备')


def number(text):
    if re.fullmatch(r'\d+(?:\.\d+)?',text):return float(text)
    digits={'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if text in digits:return digits[text]
    if '十' in text:
        left,right=text.split('十',1)
        return digits.get(left,1)*10+digits.get(right,0)
    raise ValueError('暂不支持这种数字写法，请使用阿拉伯数字。')


def offline_plan(query):
    departments=[x for x in DEPARTMENTS if x in query]
    if len(departments)!=1:raise ValueError('请明确唯一申请部门：信息技术部、研发部或综合管理部。')
    item=next((x for x in ITEMS if x in query),None)
    if item is None and '电脑' in query:item='笔记本电脑'
    if not item:raise ValueError('请明确采购物品。')
    quantity=re.search(r'(\d+|[零一二两三四五六七八九十]+)\s*(?:台|个|件|套)',query)
    budget=re.search(r'(?:预算|上限|不超过|控制在)[^\d零一二两三四五六七八九十]{0,5}(\d+(?:\.\d+)?|[零一二两三四五六七八九十]+)\s*(万|千)?',query)
    purpose=re.search(r'(?:用于|用途[：:为]?|用来)\s*(.+?)(?:[。；;\n]|$)',query)
    missing=[]
    if not quantity:missing.append('数量')
    if not budget:missing.append('预算上限')
    if not purpose:missing.append('申请用途')
    if missing:raise ValueError('请补充'+ '、'.join(missing)+'，系统不会代填业务事实。')
    qty=number(quantity.group(1))
    amount=number(budget.group(1))*{'万':10000,'千':1000,None:1}[budget.group(2)]
    if qty!=int(qty) or amount!=int(amount):raise ValueError('数量和预算必须为整数。')
    return {'goal':'填写采购申请，人工确认后提交至本地门户并核对回执','payload':{'department':departments[0],'item':item,'quantity':int(qty),'budget':int(amount),'reason':purpose.group(1).strip(' ，,')},'route':'semantic-dom' if 'DOM' in query.upper() else 'page-tool'}
