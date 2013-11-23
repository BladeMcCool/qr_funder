import os, sys, time, datetime, random, binascii, io
from qrcode import *
from pycoin.wallet import Wallet
from pycoin.convention import tx_fee
from pycoin.services import blockchain_info
from pycoin.ecdsa import secp256k1
from pycoin.tx import Tx, UnsignedTx, TxOut, SecretExponentSolver
from pycoin import ecdsa, encoding
from jinja2 import Environment, FileSystemLoader
from optparse import OptionParser
from cdecimal import Decimal

if __name__ == '__main__':
  optparser = OptionParser()
  optparser.add_option('-p', dest='pages', type="int", default=1) #number of pages (6 per page)
  optparser.add_option('-s', dest='funding_source') #dumpprivkey on bitcoind for some address that has $$
  optparser.add_option('-a', dest='funding_amount')
  optparser.add_option('-f', dest='forced_tx_source', default=None)
  (options, args) = optparser.parse_args()
  
  if not options.funding_amount:
    print "-a for amount to fund each key with is required."
    sys.exit()

  if not options.funding_source:
    print "-s for funding source (WIF private key!) is required."
    sys.exit()

  s_per_b = 100000000
  #determine how many we plan to make ...
  per_page = 6
  # pages = 2 #will get 6 per page, so ...
  pages = options.pages
  code_per_row = 3
  rows_per_page = 2
  code_count = pages * rows_per_page * code_per_row
  fee        = 10000 #satoshis.
  
  #ensure there is enough money to do it ...
  funding_amount = Decimal(options.funding_amount)
  total = funding_amount * code_count
  total_s = int(total * s_per_b)
  print "Checking that a total of %s BTC (%s satoshis) is available ..." % (total, total_s)
  
  #which means first taking the WIF, turn to secret exponent, ask for public_pair and get BTC address from public pair ... then ask blockchain service about that address.
  satoshis = 0
  coin_sources = []  
  secret_exponent = None
  bitcoin_address_compressed = None
  
  try:
    secret_exponent = encoding.wif_to_secret_exponent(options.funding_source)
    public_pair = ecdsa.public_pair_for_secret_exponent(secp256k1.generator_secp256k1, secret_exponent)  
    bitcoin_address_compressed = encoding.public_pair_to_bitcoin_address(public_pair, compressed=True)
  except:
    print "Hrm something went wrong in trying to figure out BTC address from WIF %s" % (options.funding_source)
    sys.exit()

  try:
    if not options.forced_tx_source:
      coin_sources = blockchain_info.coin_sources_for_address(bitcoin_address_compressed)
    else:
      #forced args should combine all the info we need to run the code below ... so, value in satoshis, script, tx_hash and tx_output_n 
      #value is in satoshis. tx_output_n does appear to start at zero after all.
      #u can find a tx outputs info by putting the tx in here: https://blockchain.info/rawtx/8684f9ea9f35953d0235cd4f5c73485dcf0eeb4cada6d2f657b63bea1e425178?scripts=true
      #eg args below ... wanted to redo something that used output # 0 of this tx as a source: 8684f9ea9f35953d0235cd4f5c73485dcf0eeb4cada6d2f657b63bea1e425178, soooo from the https://blockchain.info/rawtx/8684f9ea9f35953d0235cd4f5c73485dcf0eeb4cada6d2f657b63bea1e425178?scripts=true link we got:
        #8684f9ea9f35953d0235cd4f5c73485dcf0eeb4cada6d2f657b63bea1e425178,0,500000,76a91439d61ff876886683142acf9b0235ea0bcc3ecf8788ac
      hash, tx_output_n, s_value, script = options.forced_tx_source.split(',')
      #the hash we get from rawtx will be the reverse byte order of the tx_hash that the unspent outputs thing that the pycoin normally uses (http://blockchain.info/unspent?active=%s ) reports (why?? only Satoshi knows.)
      #so we'll just put it in the form that is expected for manipulations by pycon.
      tx_hash = "".join(reversed([hash[i:i+2] for i in range(0, len(hash), 2)]))
      tx_out = TxOut(int(s_value), binascii.unhexlify(script.encode()))
      coins_source = (binascii.unhexlify(tx_hash.encode()), int(tx_output_n), tx_out)
      coin_sources.append(coins_source)
      print "NOTE: Could not verify that this source address even has enough funds, but preparing a (possibly to be rejected by network) that will source from supplied info and send change back to BTC %s address from WIF" % (bitcoin_address_compressed)
    
  except:
    print "Hrm something went wrong in trying to figure out coin sources from WIF %s" % (options.funding_source)
    sys.exit()
      
  for src in coin_sources:
    satoshis += src[2].coin_value
  print "Found %s satoshis in BTC address %s (derived from private key %s)" % (satoshis, bitcoin_address_compressed, options.funding_source)
  
  if ((satoshis - fee) < total_s):
    print "Not enough funds to create the required funding transaction. :("
    sys.exit()
    
  #generate output addresses and the html
  path     = os.path.dirname(os.path.abspath(__file__))
  savedir  = 'qr_html'
  savepath = os.path.join(path, savedir)

  #make output directory if not exists.
  if not os.path.exists(savepath):
    os.makedirs(savepath)
    
  #clean the files out of the folder:
  raw_input("Cleaning out destination path for html output (%s) .. press ENTER to continue or CTRL-C to bail."%(savepath))
  
  for delfile in os.listdir(savepath):
    file_path = os.path.join(savepath, delfile)
    try:
      #print "Would kill %s" % file_path
      if os.path.isfile(file_path):
        os.unlink(file_path)
    except Exception, e:
      pass

  j2_env  = Environment(loader=FileSystemLoader(path), trim_blocks=True )
  tmpl = j2_env.get_template('qrlayout.tmpl')
  
  tmpl_vars = { "outrows":[], "savedir": savepath, "funding_amount": funding_amount }
  row = []
  coins_to = [] ###LEFT OFF HERE append the tuples ... satoshis,btcaddy (i think, see spend.py around line 39)
  
  for i in range(code_count):
    w = Wallet.from_master_secret(bytes(bytearray(open("/dev/urandom", "rb").read(64))))

    wif = w.wif()
    btc_addr = w.bitcoin_address()
    coins_to.append((int(s_per_b*funding_amount), btc_addr))

    print "Generating for version %s ... %s .. %s" % (i, wif, w.bitcoin_address())
    qr = QRCode(border=0, box_size=10)
    qr.add_data(wif)
    im = qr.make_image(fit=True)

    im.save('%s/%s.png'%(savepath, btc_addr ))
    row.append({ 'address' : btc_addr })

    if (((i+1) % code_per_row) == 0) or (i+1 == code_count):
      #print "NEW ROW ... (i+1 = %s, len(row) = %s, code_count = %s ... %s and %s)"%(i+1, len(row), code_count, (((i+1) % len(row)) == 0), (i+1 == code_count))
      tmpl_vars['outrows'].append(row)
      row = []

  ##VERY IMPORTANT BIT ABOUT CHANGE (lol, ... ALMOST forgot about this) ... send unspent input back to source address!!!!
  unspent = satoshis - total_s
  change  = unspent - fee
  if change < 0:
    raise Exception("wtf happened? can't have negative change!")
  if change > 0:
    print "Adding change of %s back to source address %s (NOTE: THIS TX WILL HAVE %s FEE!)" % (change, bitcoin_address_compressed, fee)
    coins_to.append((change, bitcoin_address_compressed))
      
  #print "Here with tmpl_vars %s" % tmpl_vars
  html = tmpl.render(**tmpl_vars)
  f = open(savepath+'/qrlayout.html', "w")
  f.write(html)
  f.close()
  
  #prepare the transaction to fund these addresses. (code below essentially lifted from the bottom of pycoin's spend.py). Note that code does multiple input addresses. this is just cheesed down to a single.
  unsigned_tx = UnsignedTx.standard_tx(coin_sources, coins_to)
  solver = SecretExponentSolver([secret_exponent])
  new_tx = unsigned_tx.sign(solver)
  print "Created tx like %s" % (repr(new_tx))
  s = io.BytesIO()
  new_tx.stream(s)
  tx_bytes = s.getvalue()
  tx_hex = binascii.hexlify(tx_bytes).decode("utf8")
  
  #write the tx to a tx file.
  tx_f = open(savepath+'/pushtx.txt', "w")
  tx_f.write(tx_hex)
  tx_f.close()
  
  print "Job Complete"


