import pytest
from app.agent import demo_plan


def test_missing_facts_and_conflicting_departments_do_not_create_defaults():
    for query in ['研发部采购电脑','研发部和综合管理部采购3台电脑，预算18000元，用于开发测试','研发部采购3台电脑，预算18000元']:
        with pytest.raises(ValueError):
            demo_plan(query)


def test_chinese_quantity_budget_and_explicit_purpose():
    plan=demo_plan('综合管理部申请两台显示器，预算1.8万元，用于日常办公。')
    assert plan.payload.model_dump()=={'department':'综合管理部','item':'显示器','quantity':2,'budget':18000,'reason':'日常办公'}
