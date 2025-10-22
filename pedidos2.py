"""
PDV/PDV Moderno — Tkinter + ttkbootstrap (Dark Mode)
Recursos:
 - Interface moderna usando ttkbootstrap (dark theme)
 - Abas: Produtos / Venda / Configurações
 - Banco SQLite para produtos, vendas e configuração da loja
 - Impressão térmica via socket (rede) e suporte opcional python-escpos (USB/Serial)
 - Cupom com nome da loja, endereço, telefone, forma de pagamento

Requisitos:
 pip install ttkbootstrap python-escpos pillow

Observações:
 - Impressoras de rede geralmente usam porta 9100. Configure IP/porta em Configurações.
 - Para usar USB/Serial via python-escpos, informe vendor/product no campo correspondente.
 - Código de exemplo educativo: para emissão fiscal real, adapte à legislação local.

Como rodar:
 python pdv_dark_tkbootstrap.py
"""

import os
import sqlite3
import time
import socket
import traceback
import tkinter as tk
from tkinter import CENTER, ttk, messagebox

# dependências externas
try:
    import ttkbootstrap as tb # pyright: ignore[reportMissingImports]
    from ttkbootstrap.constants import * # type: ignore
except Exception:
    raise RuntimeError("Instale dependências: pip install ttkbootstrap python-escpos pillow")

try:
    from escpos.printer import Usb, Network, Serial
    ESC_POS_AVAILABLE = True
except Exception:
    ESC_POS_AVAILABLE = False

DB_FILE = 'pdv_moderno.db'

# ----------------- Banco de dados -----------------
class Database:
    def __init__(self, db_path=DB_FILE):
        self.conn = sqlite3.connect(db_path)
        self._init_db()

    def _init_db(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, name TEXT, price REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, total REAL, payment TEXT, items TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)''')
        self.conn.commit()
        # seed produtos
        c.execute('SELECT COUNT(*) FROM products')
        if c.fetchone()[0] == 0:
            sample = [
                ('001','Burguer Classico',12.5),
                ('002','Batata Frita',8.0),
                ('003','Refrigerante Lata',5.0),
            ]
            c.executemany('INSERT INTO products (code,name,price) VALUES (?,?,?)', sample)
            self.conn.commit()

    # produtos
    def list_products(self):
        c = self.conn.cursor()
        c.execute('SELECT id,code,name,price FROM products ORDER BY id')
        return c.fetchall()

    def add_product(self, code, name, price):
        c = self.conn.cursor()
        c.execute('INSERT INTO products (code,name,price) VALUES (?,?,?)', (code,name,price))
        self.conn.commit()

    def update_product(self, pid, code, name, price):
        c = self.conn.cursor()
        c.execute('UPDATE products SET code=?,name=?,price=? WHERE id=?', (code,name,price,pid))
        self.conn.commit()

    def delete_product(self, pid):
        c = self.conn.cursor()
        c.execute('DELETE FROM products WHERE id=?', (pid,))
        self.conn.commit()

    # vendas
    def save_sale(self, items, total, payment):
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        items_text = '\n'.join([f"{q}x {n} - {p:.2f}" for q,n,p in items])
        c = self.conn.cursor()
        c.execute('INSERT INTO sales (ts,total,payment,items) VALUES (?,?,?,?)', (ts,total,payment,items_text))
        self.conn.commit()

    # settings
    def set_setting(self, k, v):
        c = self.conn.cursor()
        c.execute('INSERT OR REPLACE INTO settings (k,v) VALUES (?,?)', (k,str(v)))
        self.conn.commit()

    def get_setting(self, k, default=''):
        c = self.conn.cursor()
        c.execute('SELECT v FROM settings WHERE k=?', (k,))
        r = c.fetchone()
        return r[0] if r else default

# ----------------- Impressora -----------------
class ThermalPrinter:
    def __init__(self, db: Database):
        self.db = db

    def print_receipt(self, store, items, total, payment):
        mode = self.db.get_setting('printer_mode', 'network')
        ip = self.db.get_setting('printer_ip', '192.168.0.100')
        port = int(self.db.get_setting('printer_port', '9100'))
        vendor = self.db.get_setting('printer_usb_vendor', '')
        product = self.db.get_setting('printer_usb_product', '')

        text = self._build_text(store, items, total, payment)

        if mode == 'network':
            return self._print_network(ip, port, text)
        elif mode == 'escpos_usb' and ESC_POS_AVAILABLE and vendor and product:
            return self._print_escpos_usb(int(vendor,16), int(product,16), store, items, total, payment)
        else:
            # fallback para network
            return self._print_network(ip, port, text)

    def _build_text(self, store, items, total, payment):
        name = store.get('name','Minha Loja')
        addr = store.get('address','')
        phone = store.get('phone','')
        lines = []
        lines.append(name.center(32))
        if addr: lines.append(addr.center(32))
        if phone: lines.append(('Tel: '+phone).center(32))
        lines.append('-'*32)
        for q,n,p in items:
            line = f"{q}x {n}"
            price_line = f"{p:.2f}"
            if len(line)+len(price_line) > 32:
                line = line[:32-len(price_line)-1]
            lines.append(line + ' '*(32-len(line)-len(price_line)) + price_line)
        lines.append('-'*32)
        lines.append('TOTAL' + ' '*(27) + f"{total:.2f}")
        lines.append(f"Pagamento: {payment}")
        lines.append('-'*32)
        lines.append('Obrigado!')
        lines.append('\n')
        return ('\n'.join(lines)).encode('utf-8')

    def _print_network(self, ip, port, data_bytes):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((ip, port))
                s.sendall(data_bytes)
            return True
        except Exception as e:
            raise

    def _print_escpos_usb(self, vendor, product, store, items, total, payment):
        if not ESC_POS_AVAILABLE:
            raise RuntimeError('python-escpos não disponível')
        p = Usb(vendor, product)
        p.text(store.get('name','') + '\n')
        p.text('-'*32 + '\n')
        for q,n,pr in items:
            p.text(f"{q}x {n} - {pr:.2f}\n")
        p.text('-'*32 + '\n')
        p.text(f"TOTAL: {total:.2f}\n")
        p.text(f"Pagamento: {payment}\n")
        p.cut()
        return True

# ----------------- Aplicação -----------------
class PDVApp:
    def __init__(self, root):
        self.root = root
        self.root.title('PDV Moderno')
        # estilo dark
        self.style = tb.Style(theme='darkly')
        self.db = Database()
        self.printer = ThermalPrinter(self.db)
        self.cart = []  # tuples (qty,name,price_total)
        self._build_ui()
        self._load_products()
        self._load_store()

    def _build_ui(self):
        # layout com Notebook
        self.nb = tb.Window(themename='darkly')
        # Obs: tb.Window já cria Tk root; forçar uso do fornecido
        # Em alguns ambientes, criar Notebook diretamente
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)

        # aba Produtos
        self.frm_products = ttk.Frame(self.notebook)
        self.notebook.add(self.frm_products, text='Produtos')
        self._build_products_tab()

        # aba Venda
        self.frm_sale = ttk.Frame(self.notebook)
        self.notebook.add(self.frm_sale, text='Venda')
        self._build_sale_tab()

        # aba Config
        self.frm_conf = ttk.Frame(self.notebook)
        self.notebook.add(self.frm_conf, text='Configurações')
        self._build_config_tab()

    # -------- Produtos Tab --------
    def _build_products_tab(self):
        top = ttk.Frame(self.frm_products)
        top.pack(fill='x')
        ttk.Button(top, text='Novo Produto', command=self._product_new).pack(side='left', padx=5, pady=5)
        ttk.Button(top, text='Editar Selecionado', command=self._product_edit).pack(side='left', padx=5)
        ttk.Button(top, text='Deletar Selecionado', command=self._product_delete).pack(side='left', padx=5)

        cols = ('id','code','name','price')
        self.tv_products = ttk.Treeview(self.frm_products, columns=cols, show='headings')
        for c in cols:
            self.tv_products.heading(c, text=c.title())
        self.tv_products.column('id',width=50,anchor=CENTER)
        self.tv_products.pack(fill='both', expand=True, padx=10, pady=10)

    def _load_products(self):
        for i in self.tv_products.get_children():
            self.tv_products.delete(i)
        for row in self.db.list_products():
            pid, code, name, price = row
            self.tv_products.insert('', 'end', iid=str(pid), values=(pid, code, name, f"{price:.2f}"))

    def _product_new(self):
        dlg = ProductDialog(self.root, 'Novo Produto')
        self.root.wait_window(dlg.top)
        if dlg.result:
            code,name,price = dlg.result
            try:
                self.db.add_product(code,name,float(price))
                self._load_products()
            except Exception as e:
                messagebox.showerror('Erro', str(e))

    def _product_edit(self):
        sel = self.tv_products.selection()
        if not sel: return
        pid = int(sel[0])
        c = self.db.conn.cursor()
        c.execute('SELECT code,name,price FROM products WHERE id=?',(pid,))
        row = c.fetchone()
        if not row: return
        dlg = ProductDialog(self.root, 'Editar Produto', row)
        self.root.wait_window(dlg.top)
        if dlg.result:
            code,name,price = dlg.result
            try:
                self.db.update_product(pid,code,name,float(price))
                self._load_products()
            except Exception as e:
                messagebox.showerror('Erro', str(e))

    def _product_delete(self):
        sel = self.tv_products.selection()
        if not sel: return
        pid = int(sel[0])
        if messagebox.askyesno('Confirma', 'Deseja remover o produto selecionado?'):
            self.db.delete_product(pid)
            self._load_products()

    # -------- Venda Tab --------
    def _build_sale_tab(self):
        left = ttk.Frame(self.frm_sale)
        left.pack(side='left', fill='both', expand=True, padx=10, pady=10)
        right = ttk.Frame(self.frm_sale)
        right.pack(side='right', fill='y', padx=10, pady=10)

        # lista de produtos (simples)
        cols = ('id','code','name','price')
        self.tv_sale_products = ttk.Treeview(left, columns=cols, show='headings', height=12)
        for c in cols: self.tv_sale_products.heading(c, text=c.title())
        self.tv_sale_products.pack(fill='both', expand=True)

        btns = ttk.Frame(left)
        btns.pack(fill='x')
        ttk.Label(btns, text='Quantidade').pack(side='left', padx=(5,2))
        self.qty_spin = ttk.Spinbox(btns, from_=1, to=100, width=5)
        self.qty_spin.pack(side='left')
        ttk.Button(btns, text='Adicionar ao Carrinho', command=self._add_to_cart).pack(side='left', padx=5)

        # carrinho
        ttk.Label(right, text='Carrinho').pack()
        self.lb_cart = tk.Listbox(right, width=40, height=12)
        self.lb_cart.pack()
        ttk.Button(right, text='Remover Item', command=self._remove_cart_item).pack(fill='x', pady=5)

        ttk.Label(right, text='Forma de Pagamento').pack(anchor='w')
        self.payment_var = tk.StringVar(value='Dinheiro')
        self.cb_payment = ttk.Combobox(right, values=['Dinheiro','Cartão','PIX','Vale'], textvariable=self.payment_var, state='readonly')
        self.cb_payment.pack(fill='x')

        self.total_var = tk.StringVar(value='0.00')
        ttk.Label(right, text='Total', font=('Segoe UI', 10, 'bold')).pack(pady=(10,0))
        ttk.Label(right, textvariable=self.total_var, font=('Segoe UI', 14, 'bold')).pack()

        ttk.Button(right, text='Finalizar / Imprimir', command=self._finalize).pack(fill='x', pady=8)

    def _load_products_into_sale(self):
        for i in self.tv_sale_products.get_children():
            self.tv_sale_products.delete(i)
        for row in self.db.list_products():
            pid, code, name, price = row
            self.tv_sale_products.insert('', 'end', iid=str(pid), values=(pid, code, name, f"{price:.2f}"))

    def _add_to_cart(self):
        sel = self.tv_sale_products.selection()
        if not sel:
            messagebox.showinfo('Aviso', 'Selecione um produto')
            return
        pid = int(sel[0])
        qty = int(self.qty_spin.get())
        c = self.db.conn.cursor()
        c.execute('SELECT name,price FROM products WHERE id=?',(pid,))
        row = c.fetchone()
        if not row: return
        name, price = row
        total_price = qty * price
        self.cart.append((qty, name, total_price))
        self.lb_cart.insert('end', f"{qty}x {name} - {total_price:.2f}")
        self._update_total()

    def _remove_cart_item(self):
        sel = self.lb_cart.curselection()
        if not sel: return
        idx = sel[0]
        self.lb_cart.delete(idx)
        self.cart.pop(idx)
        self._update_total()

    def _update_total(self):
        total = sum([p for _,_,p in self.cart])
        self.total_var.set(f"{total:.2f}")

    def _finalize(self):
        if not self.cart:
            messagebox.showinfo('Aviso','Carrinho vazio')
            return
        payment = self.payment_var.get()
        total = sum([p for _,_,p in self.cart])
        # salvar
        self.db.save_sale(self.cart, total, payment)
        # imprimir
        store = {'name':self.db.get_setting('store_name','Minha Loja'),
                 'address':self.db.get_setting('store_address',''),
                 'phone':self.db.get_setting('store_phone','')}
        try:
            self.printer.print_receipt(store, self.cart, total, payment)
            messagebox.showinfo('Sucesso','Venda salva e impressão enviada')
        except Exception as e:
            messagebox.showerror('Erro Impressão', f"Falha ao imprimir:\n{e}")
        # limpar
        self.cart.clear()
        self.lb_cart.delete(0,'end')
        self._update_total()

    # -------- Config Tab --------
    def _build_config_tab(self):
        frm = self.frm_conf
        pad = {'padx':8,'pady':6}
        ttk.Label(frm, text='Dados da Loja', font=('Segoe UI', 10, 'bold')).grid(row=0,column=0,sticky='w',**pad)
        ttk.Label(frm, text='Nome').grid(row=1,column=0,sticky='w',**pad)
        self.e_store_name = ttk.Entry(frm)
        self.e_store_name.grid(row=1,column=1,sticky='ew',**pad)

        ttk.Label(frm, text='Endereço').grid(row=2,column=0,sticky='w',**pad)
        self.e_store_addr = ttk.Entry(frm)
        self.e_store_addr.grid(row=2,column=1,sticky='ew',**pad)

        ttk.Label(frm, text='Telefone').grid(row=3,column=0,sticky='w',**pad)
        self.e_store_phone = ttk.Entry(frm)
        self.e_store_phone.grid(row=3,column=1,sticky='ew',**pad)

        ttk.Label(frm, text='Printer Mode').grid(row=4,column=0,sticky='w',**pad)
        self.pm_var = tk.StringVar(value='network')
        self.cb_printer_mode = ttk.Combobox(frm, values=['network','escpos_usb'], textvariable=self.pm_var, state='readonly')
        self.cb_printer_mode.grid(row=4,column=1,sticky='ew',**pad)

        ttk.Label(frm, text='Printer IP').grid(row=5,column=0,sticky='w',**pad)
        self.e_printer_ip = ttk.Entry(frm)
        self.e_printer_ip.grid(row=5,column=1,sticky='ew',**pad)

        ttk.Label(frm, text='Printer Port').grid(row=6,column=0,sticky='w',**pad)
        self.e_printer_port = ttk.Entry(frm)
        self.e_printer_port.grid(row=6,column=1,sticky='ew',**pad)

        ttk.Label(frm, text='USB Vendor (hex)').grid(row=7,column=0,sticky='w',**pad)
        self.e_usb_vendor = ttk.Entry(frm)
        self.e_usb_vendor.grid(row=7,column=1,sticky='ew',**pad)

        ttk.Label(frm, text='USB Product (hex)').grid(row=8,column=0,sticky='w',**pad)
        self.e_usb_product = ttk.Entry(frm)
        self.e_usb_product.grid(row=8,column=1,sticky='ew',**pad)

        ttk.Button(frm, text='Salvar Configuração', command=self._save_config).grid(row=9,column=0,columnspan=2, pady=12)

        # expand
        frm.columnconfigure(1, weight=1)

    def _save_config(self):
        self.db.set_setting('store_name', self.e_store_name.get())
        self.db.set_setting('store_address', self.e_store_addr.get())
        self.db.set_setting('store_phone', self.e_store_phone.get())
        self.db.set_setting('printer_mode', self.pm_var.get())
        self.db.set_setting('printer_ip', self.e_printer_ip.get())
        self.db.set_setting('printer_port', self.e_printer_port.get())
        self.db.set_setting('printer_usb_vendor', self.e_usb_vendor.get())
        self.db.set_setting('printer_usb_product', self.e_usb_product.get())
        messagebox.showinfo('Sucesso', 'Configurações salvas')

    def _load_store(self):
        self.e_store_name.delete(0,'end'); self.e_store_name.insert(0, self.db.get_setting('store_name','Minha Loja'))
        self.e_store_addr.delete(0,'end'); self.e_store_addr.insert(0, self.db.get_setting('store_address','Rua Exemplo, 123'))
        self.e_store_phone.delete(0,'end'); self.e_store_phone.insert(0, self.db.get_setting('store_phone','(11) 99999-9999'))
        self.pm_var.set(self.db.get_setting('printer_mode','network'))
        self.e_printer_ip.delete(0,'end'); self.e_printer_ip.insert(0, self.db.get_setting('printer_ip','192.168.0.100'))
        self.e_printer_port.delete(0,'end'); self.e_printer_port.insert(0, self.db.get_setting('printer_port','9100'))
        self.e_usb_vendor.delete(0,'end'); self.e_usb_vendor.insert(0, self.db.get_setting('printer_usb_vendor',''))
        self.e_usb_product.delete(0,'end'); self.e_usb_product.insert(0, self.db.get_setting('printer_usb_product',''))
        # carregar produtos na aba venda
        self._load_products_into_sale()

# ----------------- Dialog de Produto -----------------
class ProductDialog:
    def __init__(self, parent, title, data=None):
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.result = None
        ttk.Label(self.top, text='Código').grid(row=0,column=0,padx=6,pady=6)
        self.e_code = ttk.Entry(self.top)
        self.e_code.grid(row=0,column=1,padx=6,pady=6)
        ttk.Label(self.top, text='Nome').grid(row=1,column=0,padx=6,pady=6)
        self.e_name = ttk.Entry(self.top)
        self.e_name.grid(row=1,column=1,padx=6,pady=6)
        ttk.Label(self.top, text='Preço').grid(row=2,column=0,padx=6,pady=6)
        self.e_price = ttk.Entry(self.top)
        self.e_price.grid(row=2,column=1,padx=6,pady=6)
        if data:
            code,name,price = data
            self.e_code.insert(0,code)
            self.e_name.insert(0,name)
            self.e_price.insert(0,str(price))
        ttk.Button(self.top, text='Salvar', command=self._on_save).grid(row=3,column=0,columnspan=2,pady=8)

    def _on_save(self):
        code = self.e_code.get().strip()
        name = self.e_name.get().strip()
        price = self.e_price.get().strip()
        if not code or not name or not price:
            messagebox.showwarning('Atenção','Preencha todos os campos')
            return
        try:
            float(price)
        except ValueError:
            messagebox.showwarning('Atenção','Preço inválido')
            return
        self.result = (code,name,price)
        self.top.destroy()

# ----------------- MAIN -----------------
if __name__ == '__main__':
    root = tk.Tk()
    root.geometry('1000x650')
    app = PDVApp(root)
    root.mainloop()