#!/usr/bin/env python3

import argparse
import os
import sys
import itertools

# input file data with illegal characters removed,
# converted according to JESD71 Table 2
# 6 bits per index
inputSymbols = []

# decompressed output data
# 8 bits per index
outputBytes = []

# uncompressed data length in bytes
uncompressed_len = 0

# bit index tracker used by get_bit()
next_bitIdx = 0

# convert according to JESD71 Table 2:
# '0' - '9' : 0b000000 - 0b001001
# 'A' - 'Z' : 0b001010 - 0b100011
# 'a' - 'z' : 0b100100 - 0b111101
# '_'       : 0b111110
# '@'       : 0b111111
# error     : -1
def convert_input_char_to_binary(inChar):
	if ((ord(inChar) >= ord('0')) and
		(ord(inChar) <= ord('9'))):
		outVal = ord(inChar) - ord('0')
	elif ((ord(inChar) >= ord('A')) and
		  (ord(inChar) <= ord('Z'))):
		outVal = ord(inChar) - ord('A') + 10
	elif ((ord(inChar) >= ord('a')) and
		  (ord(inChar) <= ord('z'))):
		outVal = ord(inChar) - ord('a') + 36
	elif (ord(inChar) == ord('_')):
		outVal = 62
	elif (ord(inChar) == ord('@')):
		outVal = 63
	else:
		# illegal char, mark to skip
		outVal = -1

	return outVal


# get the least significant bit of the least significant symbol where bit 0 of
# symbol 0 has the lowest value.
# the index is updated for each bit returned.
#
# returns bitvalue [0, 1] or -1 if end of list is reached
def get_bit():
	global next_bitIdx

	symIdx = int(next_bitIdx / 6)
	bitSubIdx = int(next_bitIdx % 6)

	if (symIdx >= len(inputSymbols)):
		retVal = -1
	else:
		if ((inputSymbols[symIdx] &
			 (1 << bitSubIdx)) > 0):
			retVal = 1
		else:
			retVal = 0

		next_bitIdx = (next_bitIdx + 1)

	return retVal;


# parse inputfile and write uncompressed data to outputfile
#
# when outputDirReversed is False, the lowest output address is at the beginning of
# a line; otherwise the lowest address is at the end of a line
def parse_input(inputfile,
				outputfile,
				outputDirReversed):
	searchForFirstAt = True
	searchForFirstLiteral = True

	with inputfile as f:
		for c in itertools.chain.from_iterable(f):
			o = convert_input_char_to_binary(c)
			
			# ignore anything upto and including the first '@'
			if (searchForFirstAt):
				if (o == 63):
					searchForFirstAt = False

				continue

			if ((o >= 0) and
				(o <= 63)):
				inputSymbols.append(o)

		# extract 32-bit uncompressed length
		uncompressed_len = 0;
		for byteWriteIdx in range(0, 4, 1):
			for bitWriteIdx in range(0, 8, 1):
				bit = get_bit()
				if (bit < 0):
					print('ran out of bits while reading uncompressed length')
					exit()

				uncompressed_len |= (bit << ((8 * byteWriteIdx) + bitWriteIdx))

		outputIdx = 0
		while (outputIdx < uncompressed_len):
			# first bit of an object determines it's type
			bit = get_bit()
			if (bit < 0):
				print('ran out of bits before enough output data was collected')
				exit()
			elif (bit >= 1):
				# repeat object
				if (searchForFirstLiteral):
					print('expecting first object to be a literal, found repeat instead')
					exit()

				# take outPutIdx as offset of the first repeated byte
				# 
				# calculate N as the smallest number of bits (in the range 1..13 ) that can
				# represent the offset
				repeatWriteOffset = outputIdx
				N = int.bit_length(repeatWriteOffset)
				N = min(max(N, 1), 13)

				# read out the offset, this value gets subtracted from the current output
				# index in order to obtain from where the repeat pattern starts
				offset = 0
				for bitWriteIdx in range(0, N, 1):
					bit = get_bit()
					if (bit < 0):
						print('unexpected end of bits while reading repeat object')
						exit()

					offset |= (bit << bitWriteIdx)

				# read out the following 8 bits, this is the length (in the range 4..255)
				# of the section to repeat.
				#
				# the standard is a bit broken in this regard - if input has a literal
				# followed by a repeat block as it's first contents, repLen can not be
				# greater than 3. Check that repLen is greater than 3 instead of 4.
				repLen = 0
				for bitWriteIdx in range(0, 8, 1):
					bit = get_bit()
					if (bit < 0):
						print('unexpected end of bits while reading repeat object')
						exit()

					repLen |= (bit << bitWriteIdx)

				# sanity check offset and length
				if (offset > repeatWriteOffset):
					print('repeat object has offset field that causes negative data index')
					exit()

				if (repLen < 3):
					print('repeat object has length field less than 3')
					exit()

				# not clear from the standard if a repeat object can repeat the bytes it
				# has just written or not.
				# 
				# this implementation assumes that it's ok, and will allow it.

				byteCopyIdx = (repeatWriteOffset - offset)
				while ((repLen > 0) and
					   (outputIdx < uncompressed_len)):
					outputBytes.append(outputBytes[byteCopyIdx])
					outputIdx += 1
					byteCopyIdx += 1
					repLen -= 1

			else:
				# literal object
				searchForFirstLiteral = False

				for byteWriteIdx in range(0, 3, 1):

					byteVal = 0
					for bitWriteIdx in range(0, 8, 1):
						bit = get_bit()
						if (bit < 0):
							print('unexpected end of bits while reading literal object')
							exit()

						byteVal |= (bit << bitWriteIdx)

					outputBytes.append(byteVal)
					outputIdx += 1

	with outputfile as f:
		oneLine = ""
		colCnt = 0

		for i in range(0, uncompressed_len, 1):
			if (outputDirReversed):
				oneLine = (hex(outputBytes[i]).upper()[2:].zfill(2) + ' ') + oneLine
			else:
				oneLine = oneLine + (hex(outputBytes[i]).upper()[2:].zfill(2) + ' ')
			
			colCnt += 1
			if (colCnt >= 32):
				print(oneLine, file=f)
				colCnt = 0
				oneLine = ""

		# flush out the last unfinished line
		if (colCnt != 0):
			if (outputDirReversed):
				# first pad the left side of the line
				oneLine = ("   " * (32 - colCnt)) + oneLine;

			print(oneLine, file=f)


parser = argparse.ArgumentParser(
	description = 'decompress ACA-compressed data of one boolean array object')

parser.add_argument('--infile',
					type=argparse.FileType('r', encoding='UTF-8'),
					required=True,
					help="input file")

parser.add_argument('--reverse_output_line_dir', 
					required=False,
					action='store_true',
					help="output data index 0 begins from the right margin")

parser.add_argument('--outfile',
					type=argparse.FileType('w', encoding='UTF-8'),
					required=True,
					help="output file")

args = parser.parse_args()

if ((not args.infile) or
	(not args.outfile)):
	print(parser.format_help())
	args.infile.close()
	args.outfile.close()
	exit()

searchForFirstAt = True
parse_input(args.infile,
			args.outfile,
			args.reverse_output_line_dir)

args.infile.close()
args.outfile.close()

exit()