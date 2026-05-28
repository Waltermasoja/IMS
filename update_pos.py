import re

with open('templates/inventory/simple_pos.html', 'r') as f:
    content = f.read()

# Add style block at the top of content block
style_block = """{% block content %}
<style>
  .modern-select {
    -webkit-appearance: none;
    appearance: none;
    background-color: #ffffff !important;
    background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e");
    background-position: right 0.5rem center;
    background-repeat: no-repeat;
    background-size: 1.5em 1.5em;
    padding-right: 2.5rem;
  }
  .modern-input {
    -webkit-appearance: none;
    appearance: none;
    background-color: #ffffff !important;
  }
</style>"""

content = content.replace('{% block content %}', style_block)

# Replace <select ... class="... bg-white focus:ring-2 ...">
# We'll replace the class string directly.
old_class_select_desktop = 'class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:ring-2 focus:ring-green-500 focus:outline-none"'
new_class_select_desktop = 'class="modern-select shadow-sm w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-green-500 focus:outline-none"'

old_class_select_desktop_cust = 'class="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:ring-2 focus:ring-green-500 focus:outline-none"'
new_class_select_desktop_cust = 'class="modern-select shadow-sm flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-green-500 focus:outline-none"'

old_class_input_desktop = 'class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:ring-2 focus:ring-green-500 focus:outline-none"'
new_class_input_desktop = 'class="modern-input shadow-sm w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-green-500 focus:outline-none"'

old_class_input_desktop_mono = 'class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:ring-2 focus:ring-green-500 focus:outline-none font-mono"'
new_class_input_desktop_mono = 'class="modern-input shadow-sm w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-green-500 focus:outline-none font-mono"'


old_class_select_mobile = 'class="w-full px-3 py-2 min-h-[44px] text-sm border border-gray-200 rounded-lg bg-white focus:ring-2 focus:ring-green-500 focus:outline-none"'
new_class_select_mobile = 'class="modern-select shadow-sm w-full px-3 py-2 min-h-[44px] text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-green-500 focus:outline-none"'

old_class_select_mobile_cust = 'class="flex-1 px-3 py-2 min-h-[44px] text-sm border border-gray-200 rounded-lg bg-white focus:ring-2 focus:ring-green-500 focus:outline-none"'
new_class_select_mobile_cust = 'class="modern-select shadow-sm flex-1 px-3 py-2 min-h-[44px] text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-green-500 focus:outline-none"'

old_class_input_mobile = 'class="w-full px-3 py-2 min-h-[44px] text-sm border border-gray-200 rounded-lg bg-white focus:ring-2 focus:ring-green-500 focus:outline-none"'
new_class_input_mobile = 'class="modern-input shadow-sm w-full px-3 py-2 min-h-[44px] text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-green-500 focus:outline-none"'

old_class_input_mobile_mono = 'class="w-full px-3 py-2 min-h-[44px] text-sm border border-gray-200 rounded-lg bg-white focus:ring-2 focus:ring-green-500 focus:outline-none font-mono"'
new_class_input_mobile_mono = 'class="modern-input shadow-sm w-full px-3 py-2 min-h-[44px] text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-green-500 focus:outline-none font-mono"'


# Replace selectively
content = content.replace(old_class_select_desktop, new_class_select_desktop, 2) # Terms, Tender
content = content.replace(old_class_input_desktop_mono, new_class_input_desktop_mono, 1) # Tender ref
content = content.replace(old_class_select_desktop_cust, new_class_select_desktop_cust, 1) # Customer
content = content.replace(old_class_input_desktop, new_class_input_desktop, 3) # Due date, deposit, discount

content = content.replace(old_class_select_mobile, new_class_select_mobile, 2) # Terms, Tender mobile
content = content.replace(old_class_input_mobile_mono, new_class_input_mobile_mono, 1) # Tender ref mobile
content = content.replace(old_class_select_mobile_cust, new_class_select_mobile_cust, 1) # Customer mobile
content = content.replace(old_class_input_mobile, new_class_input_mobile, 3) # Due date, deposit, discount mobile

with open('templates/inventory/simple_pos.html', 'w') as f:
    f.write(content)

print("Updated simple_pos.html successfully.")
